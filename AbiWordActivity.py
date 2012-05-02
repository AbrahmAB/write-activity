# Copyright (C) 2006 by Martin Sevior
# Copyright (C) 2006-2007 Marc Maurer <uwog@uwog.net>
# Copyright (C) 2007, One Laptop Per Child
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from gettext import gettext as _
import logging
import os

# Abiword needs this to happen as soon as possible
import gobject
gobject.threads_init()

import gtk
import telepathy
import telepathy.client

from abiword import Canvas

from sugar.activity import activity
from sugar.activity.widgets import StopButton
from sugar.activity.widgets import ActivityToolbarButton
from sugar.activity.activity import get_bundle_path

from sugar import mime

from sugar.graphics.toolbutton import ToolButton
from sugar.graphics.toolbarbox import ToolbarButton, ToolbarBox
from sugar.graphics import style

from toolbar import EditToolbar
from toolbar import ViewToolbar
from toolbar import TextToolbar
from toolbar import ListToolbar
from toolbar import InsertToolbar
from toolbar import ParagraphToolbar
from widgets import ExportButtonFactory
from port import chooser
import speech
from speechtoolbar import SpeechToolbar

logger = logging.getLogger('write-activity')


class AbiWordActivity(activity.Activity):

    def __init__(self, handle):
        activity.Activity.__init__(self, handle)

        # abiword uses the current directory for all its file dialogs
        os.chdir(os.path.expanduser('~'))

        # create our main abiword canvas
        self.abiword_canvas = Canvas()

        toolbar_box = ToolbarBox()

        self.activity_button = ActivityToolbarButton(self)
        toolbar_box.toolbar.insert(self.activity_button, -1)

        separator = gtk.SeparatorToolItem()
        separator.show()
        self.activity_button.props.page.insert(separator, 2)
        ExportButtonFactory(self, self.abiword_canvas)
        self.activity_button.show()

        edit_toolbar = ToolbarButton()
        edit_toolbar.props.page = EditToolbar(self, toolbar_box)
        edit_toolbar.props.icon_name = 'toolbar-edit'
        edit_toolbar.props.label = _('Edit')
        toolbar_box.toolbar.insert(edit_toolbar, -1)

        view_toolbar = ToolbarButton()
        view_toolbar.props.page = ViewToolbar(self.abiword_canvas)
        view_toolbar.props.icon_name = 'toolbar-view'
        view_toolbar.props.label = _('View')
        toolbar_box.toolbar.insert(view_toolbar, -1)

        separator = gtk.SeparatorToolItem()
        toolbar_box.toolbar.insert(separator, -1)

        text_toolbar = ToolbarButton()
        text_toolbar.props.page = TextToolbar(self.abiword_canvas)
        text_toolbar.props.icon_name = 'format-text'
        text_toolbar.props.label = _('Text')
        toolbar_box.toolbar.insert(text_toolbar, -1)

        para_toolbar = ToolbarButton()
        para_toolbar.props.page = ParagraphToolbar(self.abiword_canvas)
        para_toolbar.props.icon_name = 'paragraph-bar'
        para_toolbar.props.label = _('Paragraph')
        toolbar_box.toolbar.insert(para_toolbar, -1)

        list_toolbar = ToolbarButton()
        list_toolbar.props.page = ListToolbar(self.abiword_canvas)
        list_toolbar.props.icon_name = 'toolbar-bulletlist'
        list_toolbar.props.label = _('Bullet List')
        toolbar_box.toolbar.insert(list_toolbar, -1)

        insert_toolbar = ToolbarButton()
        insert_toolbar.props.page = InsertToolbar(self.abiword_canvas)
        insert_toolbar.props.icon_name = 'insert-table'
        insert_toolbar.props.label = _('Table')
        toolbar_box.toolbar.insert(insert_toolbar, -1)

        separator = gtk.SeparatorToolItem()
        toolbar_box.toolbar.insert(separator, -1)

        image = ToolButton('insert-picture')
        image.set_tooltip(_('Insert Image'))
        self._image_id = image.connect('clicked', self._image_cb)
        toolbar_box.toolbar.insert(image, -1)

        palette = image.get_palette()
        content_box = gtk.VBox()
        palette.set_content(content_box)
        image_floating_checkbutton = gtk.CheckButton(_('Floating'))
        image_floating_checkbutton.connect('toggled',
                self._image_floating_checkbutton_toggled_cb)
        content_box.pack_start(image_floating_checkbutton)
        content_box.show_all()
        self.floating_image = False

        if speech.supported:
            self.speech_toolbar_button = ToolbarButton(icon_name='speak')
            toolbar_box.toolbar.insert(self.speech_toolbar_button, -1)
            self.speech_toolbar = SpeechToolbar(self)
            self.speech_toolbar_button.set_page(self.speech_toolbar)
            self.speech_toolbar_button.show()

        separator = gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        separator.show()
        toolbar_box.toolbar.insert(separator, -1)

        stop = StopButton(self)
        toolbar_box.toolbar.insert(stop, -1)

        toolbar_box.show_all()
        self.set_toolbar_box(toolbar_box)

        self.set_canvas(self.abiword_canvas)
        self.abiword_canvas.connect_after('map-event', self.__map_event_cb)
        self.abiword_canvas.show()
        self.connect_after('map-event', self.__map_activity_event_cb)

        self.abiword_canvas.connect('size-allocate', self.size_allocate_cb)

    def size_allocate_cb(self, abi, alloc):
        gobject.idle_add(abi.queue_draw)

    def __map_event_cb(self, event, activity):
        logger.debug('__map_event_cb')

        # no ugly borders please
        self.abiword_canvas.set_property("shadow-type", gtk.SHADOW_NONE)

        # we only do per-word selections (when using the mouse)
        self.abiword_canvas.set_word_selections(True)

        # we want a nice border so we can select paragraphs easily
        self.abiword_canvas.set_show_margin(True)

        # activity sharing
        self.participants = {}
        self.joined = False

        self.connect('shared', self._shared_cb)

        if self._shared_activity:
            # we are joining the activity
            logger.error('We are joining an activity')
            self.connect('joined', self._joined_cb)
            self._shared_activity.connect('buddy-joined',
                    self._buddy_joined_cb)
            self._shared_activity.connect('buddy-left', self._buddy_left_cb)
            if self.get_shared():
#                # oh, OK, we've already joined
                self._joined_cb()
        else:
            # we are creating the activity
            logger.error("We are creating an activity")

    def __map_activity_event_cb(self, event, activity):
        # set custom keybindings for Write
        # we do it later because have problems if done before - OLPC #11049
        logger.error('Loading keybindings')
        keybindings_file = os.path.join(get_bundle_path(), 'keybindings.xml')
        self.abiword_canvas.invoke_cmd(
                'com.abisource.abiword.loadbindings.fromURI',
                keybindings_file, 0, 0)
        # set default font
        self.abiword_canvas.select_all()
        # get_selection return content and length
        if self.abiword_canvas.get_selection('text/plain')[1] == 0:
            logging.error('Setting default font to Sans in new documents')
            self.abiword_canvas.set_font_name('Sans')
        self.abiword_canvas.moveto_bod()

    def get_preview(self):
        if not hasattr(self.abiword_canvas, 'render_page_to_image'):
            return activity.Activity.get_preview(self)

        pixbuf = self.abiword_canvas.render_page_to_image(1)
        pixbuf = pixbuf.scale_simple(style.zoom(300), style.zoom(225),
                                     gtk.gdk.INTERP_BILINEAR)

        preview_data = []

        def save_func(buf, data):
            data.append(buf)

        pixbuf.save_to_callback(save_func, 'png', user_data=preview_data)
        preview_data = ''.join(preview_data)

        return preview_data

    def _shared_cb(self, activity):
        logger.error('My Write activity was shared')
        self._sharing_setup()

        self._shared_activity.connect('buddy-joined', self._buddy_joined_cb)
        self._shared_activity.connect('buddy-left', self._buddy_left_cb)

        channel = self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES]
        logger.error('This is my activity: offering a tube...')
        id = channel.OfferDBusTube('com.abisource.abiword.abicollab', {})
        logger.error('Tube address: %s', channel.GetDBusTubeAddress(id))

    def _sharing_setup(self):
        logger.debug("_sharing_setup()")

        if self._shared_activity is None:
            logger.error('Failed to share or join activity')
            return

        self.conn = self._shared_activity.telepathy_conn
        self.tubes_chan = self._shared_activity.telepathy_tubes_chan
        self.text_chan = self._shared_activity.telepathy_text_chan
        self.tube_id = None
        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal(
                'NewTube', self._new_tube_cb)

    def _list_tubes_reply_cb(self, tubes):
        for tube_info in tubes:
            self._new_tube_cb(*tube_info)

    def _list_tubes_error_cb(self, e):
        logger.error('ListTubes() failed: %s', e)

    def _joined_cb(self, activity):
        logger.error("_joined_cb()")
        if not self._shared_activity:
            return

        self.joined = True
        logger.error('Joined an existing Write session')
        self._sharing_setup()

        logger.error('This is not my activity: waiting for a tube...')
        self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES].ListTubes(
            reply_handler=self._list_tubes_reply_cb,
            error_handler=self._list_tubes_error_cb)

    def _new_tube_cb(self, id, initiator, type, service, params, state):
        logger.error('New tube: ID=%d initiator=%d type=%d service=%s '
                     'params=%r state=%d', id, initiator, type, service,
                     params, state)

        if self.tube_id is not None:
            # We are already using a tube
            return

        if type != telepathy.TUBE_TYPE_DBUS or \
                service != "com.abisource.abiword.abicollab":
            return

        channel = self.tubes_chan[telepathy.CHANNEL_TYPE_TUBES]

        if state == telepathy.TUBE_STATE_LOCAL_PENDING:
            channel.AcceptDBusTube(id)

        # look for the initiator's D-Bus unique name
        initiator_dbus_name = None
        dbus_names = channel.GetDBusNames(id)
        for handle, name in dbus_names:
            if handle == initiator:
                logger.error('found initiator D-Bus name: %s', name)
                initiator_dbus_name = name
                break

        if initiator_dbus_name is None:
            logger.error('Unable to get the D-Bus name of the tube initiator')
            return

        cmd_prefix = 'com.abisource.abiword.abicollab.olpc.'
        # pass this tube to abicollab
        address = channel.GetDBusTubeAddress(id)
        if self.joined:
            logger.error('Passing tube address to abicollab (join): %s',
                    address)
            self.abiword_canvas.invoke_cmd(cmd_prefix + 'joinTube',
                    address, 0, 0)
            # The intiator of the session has to be the first passed
            # to the Abicollab backend.
            logger.error('Adding the initiator to the session: %s',
                    initiator_dbus_name)
            self.abiword_canvas.invoke_cmd(cmd_prefix + 'buddyJoined',
                    initiator_dbus_name, 0, 0)
        else:
            logger.error('Passing tube address to abicollab (offer): %s',
                    address)
            self.abiword_canvas.invoke_cmd(cmd_prefix + 'offerTube', address,
                    0, 0)
        self.tube_id = id

        channel.connect_to_signal('DBusNamesChanged',
            self._on_dbus_names_changed)

        self._on_dbus_names_changed(id, dbus_names, [])

    def _on_dbus_names_changed(self, tube_id, added, removed):
        """
        We call com.abisource.abiword.abicollab.olpc.buddy{Joined,Left}
        according members of the D-Bus tube. That's why we don't add/remove
        buddies in _buddy_{joined,left}_cb.
        """
        logger.error('_on_dbus_names_changed')
#        if tube_id == self.tube_id:
        cmd_prefix = 'com.abisource.abiword.abicollab.olpc'
        for handle, bus_name in added:
            logger.error('added handle: %s, with dbus_name: %s',
                    handle, bus_name)
            self.abiword_canvas.invoke_cmd(cmd_prefix + '.buddyJoined',
                    bus_name, 0, 0)
            self.participants[handle] = bus_name

    def _on_members_changed(self, message, added, removed, local_pending,
                            remote_pending, actor, reason):
        logger.error("_on_members_changed")
        for handle in removed:
            bus_name = self.participants.pop(handle, None)
            if bus_name is None:
                # FIXME: that shouldn't happen so probably hide another bug.
                # Should be investigated
                continue

            cmd_prefix = 'com.abisource.abiword.abicollab.olpc'
            logger.error('removed handle: %d, with dbus name: %s', handle,
                         bus_name)
            self.abiword_canvas.invoke_cmd(cmd_prefix + '.buddyLeft',
                    bus_name, 0, 0)

    def _buddy_joined_cb(self, activity, buddy):
        logger.error('buddy joined with object path: %s', buddy.object_path())

    def _buddy_left_cb(self, activity, buddy):
        logger.error('buddy left with object path: %s', buddy.object_path())

    def read_file(self, file_path):
        logging.debug('AbiWordActivity.read_file: %s, mimetype: %s',
                file_path, self.metadata['mime_type'])
        if self._is_plain_text(self.metadata['mime_type']):
            self.abiword_canvas.load_file('file://' + file_path, 'text/plain')
        else:
            # we pass no mime/file type, let libabiword autodetect it,
            # so we can handle multiple file formats
            self.abiword_canvas.load_file('file://' + file_path, '')

    def write_file(self, file_path):
        logging.debug('AbiWordActivity.write_file: %s, mimetype: %s',
            file_path, self.metadata['mime_type'])
        # if we were editing a text file save as plain text
        if self._is_plain_text(self.metadata['mime_type']):
            logger.debug('Writing file as type source (text/plain)')
            self.abiword_canvas.save('file://' + file_path, 'text/plain', '')
        else:
            #if the file is new, save in .odt format
            if self.metadata['mime_type'] == '':
                self.metadata['mime_type'] = \
                        'application/vnd.oasis.opendocument.text'

            # Abiword can't save in .doc format, save in .rtf instead
            if self.metadata['mime_type'] == 'application/msword':
                self.metadata['mime_type'] = 'application/rtf'

            self.abiword_canvas.save('file://' + file_path,
                    self.metadata['mime_type'], '')

        self.metadata['fulltext'] = self.abiword_canvas.get_content(
            extension_or_mimetype=".txt")[:3000]

    def _is_plain_text(self, mime_type):
        # These types have 'text/plain' in their mime_parents  but we need
        # use it like rich text
        if mime_type in ['application/rtf', 'text/rtf', 'text/html']:
            return False

        mime_parents = mime.get_mime_parents(self.metadata['mime_type'])
        return self.metadata['mime_type'] in ['text/plain', 'text/csv'] or \
               'text/plain' in mime_parents

    def _image_floating_checkbutton_toggled_cb(self, checkbutton):
        self.floating_image = checkbutton.get_active()

    def _image_cb(self, button):

        def cb(object):
            logging.debug('ObjectChooser: %r' % object)
            self.abiword_canvas.insert_image(object.file_path,
                    self.floating_image)

        chooser.pick(parent=self.abiword_canvas.get_toplevel(),
                what=chooser.IMAGE, cb=cb)
