/*
 * Copyright 2011-2015 Blender Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "kernel_split.h"

/*
 * Note on kernel_ocl_path_trace_DirectLighting_SPLIT_KERNEL kernel.
 * This is the eighth kernel in the ray tracing logic. This is the seventh
 * of the path iteration kernels. This kernel takes care of direct lighting
 * logic. However, the "shadow ray cast" part of direct lighting is handled
 * in the next kernel.
 *
 * This kernels determines the rays for which a shadow_blocked() function associated with direct lighting should be executed.
 * Those rays for which a shadow_blocked() function for direct-lighting must be executed, are marked with flag RAY_SHADOW_RAY_CAST_DL and
 * enqueued into the queue QUEUE_SHADOW_RAY_CAST_DL_RAYS
 *
 * The input and output are as follows,
 *
 * rng_coop -----------------------------------------|--- kernel_ocl_path_trace_DirectLighting_SPLIT_KERNEL ---|--- BSDFEval_coop
 * PathState_coop -----------------------------------|                                                         |--- ISLamp_coop
 * shader_data --------------------------------------|                                                         |--- LightRay_coop
 * ray_state ----------------------------------------|                                                         |--- ray_state
 * Queue_data (QUEUE_ACTIVE_AND_REGENERATED_RAYS) ---|                                                         |
 * kg (globals + data) ------------------------------|                                                         |
 * queuesize ----------------------------------------|                                                         |
 *
 * note on shader_DL : shader_DL is neither input nor output to this kernel; shader_DL is filled and consumed in this kernel itself.
 * Note on Queues :
 * This kernel only reads from the QUEUE_ACTIVE_AND_REGENERATED_RAYS queue and processes
 * only the rays of state RAY_ACTIVE; If a ray needs to execute the corresponding shadow_blocked
 * part, after direct lighting, the ray is marked with RAY_SHADOW_RAY_CAST_DL flag.
 *
 * State of queues when this kernel is called :
 * state of queues QUEUE_ACTIVE_AND_REGENERATED_RAYS and QUEUE_HITBG_BUFF_UPDATE_TOREGEN_RAYS will be same
 * before and after this kernel call.
 * QUEUE_SHADOW_RAY_CAST_DL_RAYS queue will be filled with rays for which a shadow_blocked function must be executed, after this
 * kernel call. Before this kernel call the QUEUE_SHADOW_RAY_CAST_DL_RAYS will be empty.
 */
__kernel void kernel_ocl_path_trace_DirectLighting_SPLIT_KERNEL(
	ccl_global char *globals,
	ccl_constant KernelData *data,
	ccl_global char *shader_data,		    /* Required for direct lighting */
	ccl_global char *shader_DL,			    /* Required for direct lighting */
	ccl_global uint *rng_coop,              /* Required for direct lighting */
	ccl_global PathState *PathState_coop,   /* Required for direct lighting */
	ccl_global int *ISLamp_coop,            /* Required for direct lighting */
	ccl_global Ray *LightRay_coop,          /* Required for direct lighting */
	ccl_global BsdfEval *BSDFEval_coop,     /* Required for direct lighting */
	ccl_global char *ray_state,             /* Denotes the state of each ray */
	ccl_global int *Queue_data,             /* Queue memory */
	ccl_global int *Queue_index,            /* Tracks the number of elements in each queue */
	int queuesize                           /* Size (capacity) of each queue */
	)
{
	ccl_local unsigned int local_queue_atomics;
	if(get_local_id(0) == 0 && get_local_id(1) == 0) {
		local_queue_atomics = 0;
	}
	barrier(CLK_LOCAL_MEM_FENCE);

	char enqueue_flag = 0;
	int ray_index = get_global_id(1) * get_global_size(0) + get_global_id(0);
	ray_index = get_ray_index(ray_index, QUEUE_ACTIVE_AND_REGENERATED_RAYS, Queue_data, queuesize, 0);

#ifdef __COMPUTE_DEVICE_GPU__
	/* If we are executing on a GPU device, we exit all threads that are not required
	 * If we are executing on a CPU device, then we need to keep all threads active
	 * since we have barrier() calls later in the kernel. CPU devices,
	 * expect all threads to execute barrier statement.
	 */
	if(ray_index == QUEUE_EMPTY_SLOT)
		return;
#endif

#ifndef __COMPUTE_DEVICE_GPU__
	if(ray_index != QUEUE_EMPTY_SLOT) {
#endif
		if(IS_STATE(ray_state, ray_index, RAY_ACTIVE)) {
    		/* Load kernel globals structure and ShaderData structure */
    		KernelGlobals *kg = (KernelGlobals *)globals;
    		ccl_global ShaderData *sd = (ccl_global ShaderData *)shader_data;
    		ccl_global ShaderData *sd_DL  = (ccl_global ShaderData *)shader_DL;

			ccl_global PathState *state = &PathState_coop[ray_index];

			/* direct lighting */
#ifdef __EMISSION__
			if((kernel_data.integrator.use_direct_light && (sd_fetch(flag) & SD_BSDF_HAS_EVAL))) {
				/* sample illumination from lights to find path contribution */
				ccl_global RNG* rng = &rng_coop[ray_index];
				float light_t = path_state_rng_1D(kg, rng, state, PRNG_LIGHT);
				float light_u, light_v;
				path_state_rng_2D(kg, rng, state, PRNG_LIGHT_U, &light_u, &light_v);

#ifdef __OBJECT_MOTION__
				light_ray.time = sd->time;
#endif
				LightSample ls;
				light_sample(kg, light_t, light_u, light_v, sd_fetch(time), sd_fetch(P), state->bounce, &ls);

				Ray light_ray;
				BsdfEval L_light;
				bool is_lamp;
				if(direct_emission(kg, sd, &ls, &light_ray, &L_light, &is_lamp, state->bounce, state->transparent_bounce, sd_DL)) {
					/* write intermediate data to global memory to access from the next kernel */
					LightRay_coop[ray_index] = light_ray;
					BSDFEval_coop[ray_index] = L_light;
					ISLamp_coop[ray_index] = is_lamp;
					/// mark ray state for next shadow kernel
					ADD_RAY_FLAG(ray_state, ray_index, RAY_SHADOW_RAY_CAST_DL);
					enqueue_flag = 1;
				}
			}
#endif
		}
#ifndef __COMPUTE_DEVICE_GPU__
	}
#endif

#ifdef __EMISSION__
	/* Enqueue RAY_SHADOW_RAY_CAST_DL rays */
	enqueue_ray_index_local(ray_index, QUEUE_SHADOW_RAY_CAST_DL_RAYS, enqueue_flag, queuesize, &local_queue_atomics, Queue_data, Queue_index);
#endif
}
