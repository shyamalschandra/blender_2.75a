# This sample script demonstrates a dynamic EnumProperty with custom icons.
# The EnumProperty is populated dynamically with thumbnails of the contents of
# a chosen directory in 'enum_previews_from_directory_items'.
# Then, the same enum is displayed with different interfaces. Note that the
# generated icon previews do not have Blender IDs, which means that they can
# not be used with UILayout templates that require IDs,
# such as template_list and template_ID_preview.
#
# Other use cases:
# - make a fixed list of enum_items instead of calculating them in a function.
# - generate a single thumbnail to pass in a UILayout function as icon_value
#
# Example:
#    my_addon_icons = bpy.utils.previews.new("MyAddonIcons")
#    myicon = my_addon_icons.load("myicon", "/path/to/icon-image.png", 'IMAGE')
#    layout.operator("render.render", icon_value=int(myicon.icon_id))
#
# You can generate thumbnails of your own made icons to associate with an action

import os
import bpy


def enum_previews_from_directory_items(self, context):
    """EnumProperty callback"""
    wm = context.window_manager

    enum_items = []
    directory = wm.my_previews_dir

    # gets the already existing preview collection (defined in register func).
    pcoll = previews["main"]

    if directory == pcoll.my_previews_dir:
        return pcoll.my_previews

    print("Scanning folder: %s" % directory)

    if directory and os.path.exists(directory):
        # scan the directory for png files
        dir_contents = os.listdir(directory)
        image_paths = []
        for c in dir_contents:
            if c.lower().endswith(".png"):
                image_paths.append(c)

        for idx, img_name in enumerate(image_paths):
            # generates a thumbnail preview for a file.
            # Also works with previews for 'MOVIE', 'BLEND' and 'FONT'
            filepath = os.path.join(directory, img_name)
            thumb = pcoll.load(filepath, filepath, 'IMAGE')
            # enum item: (identifier, name, description, icon, number)
            enum_items.append((img_name, img_name, img_name, int(thumb.icon_id), idx))

    pcoll.my_previews = enum_items
    pcoll.my_previews_dir = directory
    return pcoll.my_previews


class PreviewsExamplePanel(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Previews Example Panel"
    bl_idname = "OBJECT_PT_previews"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        row = layout.row()
        row.prop(wm, "my_previews_dir")

        row = layout.row()
        row.template_icon_view(wm, "my_previews")

        row = layout.row()
        row.prop(wm, "my_previews")


previews = {}

def register():
    from bpy.types import WindowManager
    from bpy.props import (
            StringProperty,
            EnumProperty,
            )

    WindowManager.my_previews_dir = StringProperty(
            name="Folder Path",
            subtype='DIR_PATH',
            default="/d"
            )

    WindowManager.my_previews = EnumProperty(
            items=enum_previews_from_directory_items,
            )

    # Note that preview collections returned by bpy.utils.previews
    # are regular py objects - you can use them to store custom data.
    #
    # This is especially useful here, since:
    # - It avoids us regenerating the whole enum over and over.
    # - It can store enum_items' strings
    #   (remember you have to keep those strings somewhere in py,
    #   else they get freed and Blender references invalid memory!).
    import bpy.utils.previews
    pcoll = bpy.utils.previews.new("PreviewsInDirectory")
    pcoll.my_previews_dir = ""
    pcoll.my_previews = ()

    previews["main"] = pcoll

    bpy.utils.register_class(PreviewsExamplePanel)


def unregister():
    from bpy.types import WindowManager

    del WindowManager.my_previews

    for p in previews.values():
        bpy.utils.previews.remove(p)
    bpy.utils.previews.clear()

    bpy.utils.unregister_class(PreviewsExamplePanel)


if __name__ == "__main__":
    register()
