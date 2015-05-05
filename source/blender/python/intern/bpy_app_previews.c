/*
 * ***** BEGIN GPL LICENSE BLOCK *****
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
 *
 * Contributor(s): Bastien Montagne
 *
 * ***** END GPL LICENSE BLOCK *****
 */

/** \file blender/python/intern/bpy_app_previews.c
 *  \ingroup pythonintern
 *
 * This file defines a singleton py object accessed via 'bpy.app.previews',
 * which exposes low-level API for custom previews/icons.
 * It is replaced in final API by an higher-level python wrapper, that handles previews by addon,
 * and automatically release them on deletion.
 */

#include <Python.h>
#include <structmember.h>

#include "BLI_utildefines.h"

#include "RNA_types.h"
#include "RNA_access.h"

#include "BPY_extern.h"
#include "bpy_app_previews.h"
#include "bpy_rna.h"

#include "MEM_guardedalloc.h"

#include "IMB_imbuf.h"
#include "IMB_imbuf_types.h"
#include "IMB_thumbs.h"

#include "BKE_icons.h"

#include "DNA_ID.h"

#include "../generic/python_utildefines.h"

PyDoc_STRVAR(app_previews_meth_new_doc,
".. method:: new(name)\n"
"\n"
"   Generate a new empty preview, or return existing one matching ``name``.\n"
"\n"
"   :arg name: The name (unique id) identifying the preview.\n"
"   :type name: string\n"
"   :return: The Preview matching given name, or a new empty one.\n"
"   :type return: Preview\n"
);
static PyObject *app_previews_meth_new(PyObject *UNUSED(self), PyObject *args, PyObject *kw)
{
	static const char *kwlist[] = {"name", NULL};
	char *name;
	PreviewImage *prv;
	PointerRNA ptr;

	if (!PyArg_ParseTupleAndKeywords(
	        args, kw, "s:bpy.app.previews.new", (char **)kwlist,
	        &name))
	{
		return NULL;
	}

	prv = BKE_previewimg_cached_get(name);
	RNA_pointer_create(NULL, &RNA_ImagePreview, prv, &ptr);

	return pyrna_struct_CreatePyObject(&ptr);
}

PyDoc_STRVAR(app_previews_meth_load_doc,
".. method:: load(name, path, path_type, force_reload)\n"
"\n"
"   Generate a new preview from given file path, or return existing one matching ``name``.\n"
"\n"
"   :arg name: The name (unique id) identifying the preview.\n"
"   :type name: string\n"
"   :arg path: The file path to generate the preview from.\n"
"   :type path: string\n"
"   :arg path_type: The type of file, needed to generate the preview ('IMAGE', 'MOVIE', 'BLEND' or 'FONT').\n"
"   :type path_type: string\n"
"   :arg force_reload: If True, force running thumbnail manager even if preview already exists in cache.\n"
"   :type force_reload: bool\n"
"   :return: The Preview matching given name, or a new empty one.\n"
"   :type return: Preview\n"
);
static PyObject *app_previews_meth_load(PyObject *UNUSED(self), PyObject *args, PyObject *kw)
{
	static const char *kwlist[] = {"name", "path", "path_type", "force_reload", NULL};
	char *name, *path, *path_type_s;
	int path_type, force_reload = false;

	PreviewImage *prv;
	PointerRNA ptr;

	if (!PyArg_ParseTupleAndKeywords(
	        args, kw, "sss|p:bpy.app.previews.load", (char **)kwlist,
	        &name, &path, &path_type_s, &force_reload))
	{
		return NULL;
	}

	if (STREQ(path_type_s, "IMAGE")) {
		path_type = THB_SOURCE_IMAGE;
	}
	else if (STREQ(path_type_s, "MOVIE")) {
		path_type = THB_SOURCE_MOVIE;
	}
	else if (STREQ(path_type_s, "BLEND")) {
		path_type = THB_SOURCE_BLEND;
	}
	else if (STREQ(path_type_s, "FONT")) {
		path_type = THB_SOURCE_FONT;
	}
	else {
		PyErr_Format(PyExc_ValueError,
		             "bpy.app.previews.load: invalid '%' path type, only 'IMAGE', 'MOVIE', 'BLEND' and 'FONT' "
		             "are supported", path_type_s);
		return NULL;
	}

	prv = BKE_previewimg_cached_thumbnail_get(name, path, path_type, force_reload);
	RNA_pointer_create(NULL, &RNA_ImagePreview, prv, &ptr);

	return pyrna_struct_CreatePyObject(&ptr);
}

PyDoc_STRVAR(app_previews_meth_release_doc,
".. method:: release(name)\n"
"\n"
"   Release (free) a previously created preview.\n"
"\n"
"\n"
"   :arg name: The name (unique id) identifying the preview.\n"
"   :type name: string\n"
"   :return: None.\n"
);
static PyObject *app_previews_meth_release(PyObject *UNUSED(self), PyObject *args, PyObject *kw)
{
	static const char *kwlist[] = {"name", NULL};
	char *name;

	if (!PyArg_ParseTupleAndKeywords(
	        args, kw, "s:bpy.app.previews.release", (char **)kwlist,
	        &name))
	{
		return NULL;
	}

	BKE_previewimg_cached_release(name);

	Py_RETURN_NONE;
}

static struct PyMethodDef bpy_app_previews_methods[] = {
	/* Can't use METH_KEYWORDS alone, see http://bugs.python.org/issue11587 */
	{"new", (PyCFunction)app_previews_meth_new, METH_VARARGS | METH_KEYWORDS, app_previews_meth_new_doc},
	{"load", (PyCFunction)app_previews_meth_load, METH_VARARGS | METH_KEYWORDS, app_previews_meth_load_doc},
	{"release", (PyCFunction)app_previews_meth_release, METH_VARARGS | METH_KEYWORDS, app_previews_meth_release_doc},
	{NULL, NULL, 0, NULL}
};

PyDoc_STRVAR(bpy_app_previews_doc,
"This object contains basic static methods to handle cached (non-ID) previews in Blender (low-level API, \n"
"not exposed to final users).\n"
);
static struct PyModuleDef bpy_app_previews_module = {
	PyModuleDef_HEAD_INIT,
	"bpy.app._previews",
	bpy_app_previews_doc,
	0,
	bpy_app_previews_methods,
	NULL, NULL, NULL, NULL
};


PyObject *BPY_app_preview_module(void)
{
	PyObject *submodule;

	submodule = PyModule_Create(&bpy_app_previews_module);

	return submodule;
}
