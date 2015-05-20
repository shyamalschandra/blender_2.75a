# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

# Note: This will be a simple addon later, but until it gets to master, it's simpler to have it
#       as a startup module!

import bpy
from bpy.types import AssetEngine, Panel
from bpy.props import (
        StringProperty,
        BoolProperty,
        IntProperty,
        FloatProperty,
        EnumProperty,
        CollectionProperty,
        )

import binascii
import concurrent.futures as futures
import hashlib
import json
import os
import stat
import struct
import time


AMBER_DB_NAME = "__amber_db.json"
AMBER_DBK_VERSION = "version"


##########
# Helpers.

# Notes about UUIDs:
#    * UUID of an asset/variant/revision is computed once at its creation! Later changes to data do not affect it.
#    * Collision, for unlikely it is, may happen across different repositories...
#      Doubt this will be practical issue though.
#    * We keep eight first bytes of 'clear' identifier, to (try to) keep some readable uuid.

def _uuid_gen_single(used_uuids, uuid_root, h, str_arg):
    h.update(str_arg.encode())
    uuid = uuid_root + h.digest()
    uuid = uuid[:23].replace(b'\0', b'\1')  # No null chars, RNA 'bytes' use them as in regular strings... :/
    if uuid not in used_uuids:  # *Very* likely, but...
        used_uuids.add(uuid)
        return uuid
    return None


def _uuid_gen(used_uuids, uuid_root, bytes_seed, *str_args):
    h = hashlib.md5(bytes_seed)
    for arg in str_args:
        uuid = _uuid_gen_single(used_uuids, uuid_root, h, arg)
        if uuid is not None:
            return uuid
    # This is a fallback in case we'd get a collision... Should never be needed in real life!
    for i in range(100000):
        uuid = _uuid_gen_single(used_uuids, uuid_root, h, i.to_bytes(4, 'little'))
        if uuid is not None:
            return uuid
    return None  # If this happens...


def uuid_asset_gen(used_uuids, path_db, name, tags):
    uuid_root = name.encode()[:8] + b'|'
    return _uuid_gen_single(used_uuids, uuid_root, path_db.encode(), name, *tags)


def uuid_variant_gen(used_uuids, asset_uuid, name):
    uuid_root = name.encode()[:8] + b'|'
    return _uuid_gen_single(used_uuids, uuid_root, asset_uuid, name)


def uuid_revision_gen(used_uuids, variant_uuid, number, size, time):
    uuid_root = str(number).encode() + b'|'
    return _uuid_gen_single(used_uuids, uuid_root, variant_uuid, str(number), str(size), str(timestamp))


def uuid_unpack(uuid_hexstr):
    return struct.unpack("!iiii", binascii.unhexlify(uuid_hexstr).ljust(16, b'\0'))


def uuid_unpack_bytes(uuid_bytes):
    return struct.unpack("!iiii", uuid_bytes.ljust(16, b'\0'))


def uuid_pack(uuid_iv4):
    return binascii.hexlify(struct.pack("!iiii", uuid_iv4))


#############
# Amber Jobs.
class AmberJob:
    def __init__(self, executor, job_id):
        self.executor = executor
        self.job_id = job_id
        self.status = {'VALID'}
        self.progress = 0.0


class AmberJobList(AmberJob):
    @staticmethod
    def ls_repo(db_path):
        repo = None
        with open(db_path, 'r') as db_f:
            repo = json.load(db_f)
        if isinstance(repo, dict):
            repo_ver = repo.get(AMBER_DBK_VERSION, "")
            if repo_ver != "1.0.0":
                # Unsupported...
                print("WARNING: unsupported Amber repository version '%s'." % repo_ver)
                repo = None
        else:
            repo = None
        if repo is not None:
            # Convert hexa string to array of four uint32...
            # XXX will have to check endianess mess here, for now always use same one ('network' one).
            new_entries = {}
            for euuid, e in repo["entries"].items():
                new_variants = {}
                for vuuid, v in e["variants"].items():
                    new_revisions = {}
                    for ruuid, r in v["revisions"].items():
                        new_revisions[uuid_unpack(ruuid)] = r
                    new_variants[uuid_unpack(vuuid)] = v
                    v["revisions"] = new_revisions
                    ruuid = v["revision_default"]
                    v["revision_default"] = uuid_unpack(ruuid)
                new_entries[uuid_unpack(euuid)] = e
                e["variants"] = new_variants
                vuuid = e["variant_default"]
                e["variant_default"] = uuid_unpack(vuuid)
            repo["entries"] = new_entries
        print(repo)
        return repo

    @staticmethod
    def ls(path):
        repo = None
        ret = [".."]
        tmp = os.listdir(path)
        if AMBER_DB_NAME in tmp:
            # That dir is an Amber repo, we only list content define by our amber 'db'.
            repo = AmberJobList.ls_repo(os.path.join(path, AMBER_DB_NAME))
        if repo is None:
            ret += tmp
        #~ time.sleep(0.1)  # 100% Artificial Lag (c)
        return ret, repo

    @staticmethod
    def stat(root, path):
        st = os.lstat(root + path)
        #~ time.sleep(0.1)  # 100% Artificial Lag (c)
        return path, (stat.S_ISDIR(st.st_mode), st.st_size, st.st_mtime)

    def start(self):
        self.nbr = 0
        self.tot = 0
        self.ls_task = self.executor.submit(self.ls, self.root)
        self.status = {'VALID', 'RUNNING'}

    def update(self, repository, dirs):
        self.status = {'VALID', 'RUNNING'}
        if self.ls_task is not None:
            if not self.ls_task.done():
                return
            paths, repo = self.ls_task.result()
            self.ls_task = None
            self.tot = len(paths)
            repository.clear()
            dirs.clear()
            if repo is not None:
                repository.update(repo)
            for p in paths:
                self.stat_tasks.add(self.executor.submit(self.stat, self.root, p))

        done = set()
        for tsk in self.stat_tasks:
            if tsk.done():
                path, (is_dir, size, timestamp) = tsk.result()
                self.nbr += 1
                if is_dir:
                    # We only list dirs from real file system.
                    uuid = uuid_unpack_bytes((path.encode()[:8] + b"|" + bytes([self.nbr])))
                    dirs.append((path, size, timestamp, uuid))
                done.add(tsk)
        self.stat_tasks -= done

        self.progress = self.nbr / self.tot
        if not self.stat_tasks and self.ls_task is None:
            self.status = {'VALID'}

    def __init__(self, executor, job_id, root):
        super().__init__(executor, job_id)
        self.root = root

        self.ls_task = None
        self.stat_tasks = set()

        self.start()

    def __del__(self):
        # Avoid useless work!
        if self.ls_task is not None:
            self.ls_task.cancel()
        for tsk in self.stat_tasks:
            tsk.cancel()


###########################
# Main Asset Engine class.
class AssetEngineAmber(AssetEngine):
    bl_label = "Amber"

    # *Very* primitive! Only 32 tags allowed...
    def _tags_gen(self, context):
        tags = getattr(self, "tags_source", [])
        return [(tag, tag, str(prio)) for tag, prio in tags[:32]]
    tags = EnumProperty(
            items=_tags_gen,
            name="Tags",
            description="Active tags",
            options={'ENUM_FLAG'},
    )

    def __init__(self):
        self.executor = futures.ThreadPoolExecutor(8)  # Using threads for now, if issues arise we'll switch to process.
        self.jobs = {}

        self.reset()

        self.job_uuid = 1

    def __del__(self):
        # XXX This errors, saying self has no executor attribute... Suspect some py/RNA funky game. :/
        #     Even though it does not seem to be an issue, this is not nice and shall be fixed somehow.
        executor = getattr(self, "executor", None)
        if executor is not None:
            executor.shutdown(wait=False)

    ########## Various helpers ##########
    def reset(self):
        print("Amber Reset!")
        self.root = ""
        self.repo = {}
        self.dirs = []
        self.tags_source = []

        self.sortedfiltered = []

    def entry_from_uuid(self, entries, euuid, vuuid, ruuid):
        e = self.repo["entries"][euuid]
        entry = entries.entries.add()
        entry.uuid = euuid
        entry.name = e["name"]
        entry.description = e["description"]
        entry.type = {e["file_type"]}
        entry.blender_type = e["blen_type"]
        act_rev = None
        if vuuid == (0, 0, 0, 0):
            for vuuid, v in e["variants"].items():
                variant = entry.variants.add()
                variant.uuid = vuuid
                variant.name = v["name"]
                variant.description = v["description"]
                if vuuid == e["variant_default"]:
                    entry.variants.active = variant
                for ruuid, r in v["revisions"].items():
                    revision = variant.revisions.add()
                    revision.uuid = ruuid
                    #~ revision.comment = r["comment"]
                    revision.size = r["size"]
                    revision.timestamp = r["timestamp"]
                    if ruuid == v["revision_default"]:
                        variant.revisions.active = revision
                        if vuuid == e["variant_default"]:
                            act_rev = r
        else:
            v = e["variants"][vuuid]
            variant = entry.variants.add()
            variant.uuid = vuuid
            variant.name = v["name"]
            variant.description = v["description"]
            entry.variants.active = variant
            if ruuid == (0, 0, 0, 0):
                for ruuid, r in v["revisions"].items():
                    revision = variant.revisions.add()
                    revision.uuid = ruuid
                    #~ revision.comment = r["comment"]
                    revision.size = r["size"]
                    revision.timestamp = r["timestamp"]
                    if ruuid == v["revision_default"]:
                        variant.revisions.active = revision
                        act_rev = r
            else:
                r = v["revisions"][ruuid]
                revision = variant.revisions.add()
                revision.uuid = ruuid
                #~ revision.comment = r["comment"]
                revision.size = r["size"]
                revision.timestamp = r["timestamp"]
                variant.revisions.active = revision
                act_rev = r
        if act_rev:
            entry.relpath = act_rev["path"]

    ########## PY-API only ##########
    # UI header
    def draw_header(self, layout, context):
        st = context.space_data
        params = st.params

        # can be None when save/reload with a file selector open
        if params:
            is_lib_browser = params.use_library_browsing

            layout.prop(params, "display_type", expand=True, text="")
            layout.prop(params, "sort_method", expand=True, text="")

            layout.prop(params, "show_hidden", text="", icon='FILE_HIDDEN')
            layout.prop(params, "use_filter", text="", icon='FILTER')

            row = layout.row(align=True)
            row.active = params.use_filter

            if params.filter_glob:
                #if st.active_operator and hasattr(st.active_operator, "filter_glob"):
                #    row.prop(params, "filter_glob", text="")
                row.label(params.filter_glob)
            else:
                row.prop(params, "use_filter_blender", text="")
                row.prop(params, "use_filter_backup", text="")
                row.prop(params, "use_filter_image", text="")
                row.prop(params, "use_filter_movie", text="")
                row.prop(params, "use_filter_script", text="")
                row.prop(params, "use_filter_font", text="")
                row.prop(params, "use_filter_sound", text="")
                row.prop(params, "use_filter_text", text="")

            if is_lib_browser:
                row.prop(params, "use_filter_blendid", text="")
                if (params.use_filter_blendid) :
                    row.separator()
                    row.prop(params, "filter_id", text="")

            row.separator()
            row.prop(params, "filter_search", text="", icon='VIEWZOOM')

    ########## C (RNA) API ##########
    def status(self, job_id):
        if job_id:
            job = self.jobs.get(job_id, None)
            return job.status if job is not None else set()
        return {'VALID'}

    def progress(self, job_id):
        if job_id:
            job = self.jobs.get(job_id, None)
            return job.progress if job is not None else 0.0
        progress = 0.0
        nbr_jobs = 0
        for job in self.jobs.values():
            if 'RUNNING' in job.status:
                nbr_jobs += 1
                progress += job.progress
        return progress / nbr_jobs if nbr_jobs else 0.0

    def kill(self, job_id):
        if job_id:
            self.jobs.pop(job_id, None)
            return
        self.jobs.clear()

    def list_dir(self, job_id, entries):
        job = self.jobs.get(job_id, None)
        #~ print(entries.root_path, job_id, job)
        if job is not None and isinstance(job, AmberJobList):
            if job.root != entries.root_path:
                self.reset()
                self.jobs[job_id] = AmberJobList(self.executor, job_id, entries.root_path)
                self.root = entries.root_path
            else:
                job.update(self.repo, self.dirs)
        elif self.root != entries.root_path:
            self.reset()
            job_id = self.job_uuid
            self.job_uuid += 1
            self.jobs[job_id] = AmberJobList(self.executor, job_id, entries.root_path)
            self.root = entries.root_path
        if self.repo:
            entries.nbr_entries = len(self.repo["entries"])
            self.tags_source[:] = sorted(self.repo["tags"].items(), key=lambda i: i[1], reverse=True)
        else:
            entries.nbr_entries = len(self.dirs)
            self.tags_source.clear()
        return job_id

    def load_pre(self, uuids, entries):
        # Not quite sure this engine will need it in the end, but for sake of testing...
        if self.repo:
            for uuid in uuids.uuids:
                euuid = tuple(uuid.uuid_asset)
                vuuid = tuple(uuid.uuid_variant)
                ruuid = tuple(uuid.uuid_revision)
                e = self.repo["entries"][euuid]
                v = e["variants"][vuuid]
                r = v["revisions"][ruuid]

                entry = entries.entries.add()
                entry.type = {e["file_type"]}
                entry.blender_type = e["blen_type"]
                # archive part not yet implemented!
                entry.relpath = r["path"]
                entry.uuid = euuid
                var = entry.variants.add()
                var.uuid = vuuid
                rev = var.revisions.add()
                rev.uuid = ruuid
                var.revisions.active = rev
                entry.variants.active = var
            entries.root_path = self.root
            return True
        return False

    def sort_filter(self, use_sort, use_filter, params, entries):
        if use_filter:
            filter_search = params.filter_search
            self.sortedfiltered.clear()
            if self.repo:
                for key, val in self.repo["entries"].items():
                    if filter_search and filter_search not in (val["name"] + val["description"]):
                        continue
                    if params.use_filter:
                        file_type = set()
                        blen_type = set()
                        tags = set(self.tags)
                        if params.use_filter_image:
                            file_type.add('IMAGE')
                        if params.use_filter_blender:
                            file_type.add('BLENDER')
                        if params.use_filter_backup:
                            file_type.add('BACKUP')
                        if params.use_filter_movie:
                            file_type.add('MOVIE')
                        if params.use_filter_script:
                            file_type.add('SCRIPT')
                        if params.use_filter_font:
                            file_type.add('FONT')
                        if params.use_filter_sound:
                            file_type.add('SOUND')
                        if params.use_filter_text:
                            file_type.add('TEXT')
                        if params.use_filter_blendid and params.use_library_browsing:
                            file_type.add('BLENLIB')
                            blen_type = params.filter_id
                        if val["file_type"] not in file_type:
                            continue
                        if params.use_library_browsing and val["blen_type"] not in blen_type:
                            continue
                        if tags and not tags & set(val["tags"]):
                            continue
                    self.sortedfiltered.append((key, val))
            elif self.dirs:
                for path, size, timestamp, uuid in self.dirs:
                    if filter_search and filter_search not in path:
                        continue
                    if not params.show_hidden and path.startswith(".") and not path.startswith(".."):
                        continue
                    self.sortedfiltered.append((path, size, timestamp, uuid))
            use_sort = True
        entries.nbr_entries_filtered = len(self.sortedfiltered)
        if use_sort:
            if self.repo:
                if params.sort_method == 'FILE_SORT_TIME':
                    self.sortedfiltered.sort(key=lambda e: e[1]["variants"][e[1]["variant_default"]]["revisions"][e[1]["variants"][e[1]["variant_default"]]["revision_default"]]["timestamp"])
                elif params.sort_method == 'FILE_SORT_SIZE':
                    self.sortedfiltered.sort(key=lambda e: e[1]["variants"][e[1]["variant_default"]]["revisions"][e[1]["variants"][e[1]["variant_default"]]["revision_default"]]["size"])
                elif params.sort_method == 'FILE_SORT_EXTENSION':
                    self.sortedfiltered.sort(key=lambda e: e[1]["blen_type"])
                else:
                    self.sortedfiltered.sort(key=lambda e: e[1]["name"].lower())
            else:
                if params.sort_method == 'FILE_SORT_TIME':
                    self.sortedfiltered.sort(key=lambda e: e[2])
                elif params.sort_method == 'FILE_SORT_SIZE':
                    self.sortedfiltered.sort(key=lambda e: e[1])
                else:
                    self.sortedfiltered.sort(key=lambda e: e[0].lower())
            return True
        return False

    def entries_block_get(self, start_index, end_index, entries):
        if self.repo:
            print("self repo", len(self.sortedfiltered), start_index, end_index)
            for euuid, e in self.sortedfiltered[start_index:end_index]:
                self.entry_from_uuid(entries, euuid, (0, 0, 0, 0), (0, 0, 0, 0))
        else:
            print("self dirs", len(self.sortedfiltered), start_index, end_index)
            for path, size, timestamp, uuid in self.sortedfiltered[start_index:end_index]:
                entry = entries.entries.add()
                entry.type = {'DIR'}
                entry.relpath = path
                entry.uuid = uuid
                variant = entry.variants.add()
                entry.variants.active = variant
                rev = variant.revisions.add()
                rev.size = size
                rev.timestamp = timestamp
                variant.revisions.active = rev
        return True

    def entries_uuid_get(self, uuids, entries):
        if self.repo:
            for uuid in uuids.uuids:
                self.entry_from_uuid(entries, tuple(uuid.uuid_asset), tuple(uuid.uuid_variant), tuple(uuid.uuid_revision))
            return True
        return False


##########
# UI stuff
class AmberPanel():
    @classmethod
    def poll(cls, context):
        space = context.space_data
        if space and space.type == 'FILE_BROWSER':
            ae = space.asset_engine
            if ae and space.asset_engine_type == "AssetEngineAmber":
                return True
        return False


class AMBER_PT_options(Panel, AmberPanel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOLS'
    bl_category = "Asset Engine"
    bl_label = "Amber Options"

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        ae = space.asset_engine

        row = layout.row()


class AMBER_PT_tags(Panel, AmberPanel):
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOLS'
    bl_category = "Asset Engine"
    bl_label = "Tags"

    def draw(self, context):
        ae = context.space_data.asset_engine

        # Note: This is *ultra-primitive*!
        #       A good UI will most likely need new widget option anyway (template). Or maybe just some UIList...
        self.layout.props_enum(ae, "tags")


if __name__ == "__main__":  # only for live edit.
    bpy.utils.register_module(__name__)