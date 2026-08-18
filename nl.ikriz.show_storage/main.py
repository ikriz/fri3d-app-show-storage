"""Storage info app for the Fri3d Camp 2026 badge (MicroPythonOS).

Shows total / used / available space for the internal flash filesystem and for
a microSD card when one is inserted. The SD card is mounted through mpos's
SDCardManager, which puts it at /sdcard.

Drop this in as apps/nl.ikriz.storage-space/main.py.
"""

import os

import lvgl as lv
from mpos import Activity

try:
    from mpos import SDCardManager
except ImportError:
    SDCardManager = None

try:
    from mpos import NumberFormat
except ImportError:
    NumberFormat = None


UNITS = ("B", "KB", "MB", "GB", "TB")

# The internal littlefs partition is the root of the filesystem, and /sdcard is
# the SD mount point; see https://docs.micropythonos.org/architecture/filesystem/
INTERNAL_PATH = "/"
SD_PATH = "/sdcard"


def _num(value, decimals=None):
    """Format a number using the user's number-format preference."""
    if NumberFormat is not None:
        try:
            return NumberFormat.format_number(value, decimals)
        except Exception:
            pass
    if decimals:
        return "%.*f" % (decimals, value)
    return "%d" % value


def human(nbytes):
    """Format a byte count as a short human readable string."""
    size = float(nbytes)
    i = 0
    while size >= 1024.0 and i < len(UNITS) - 1:
        size /= 1024.0
        i += 1
    if i == 0:
        return "%s B" % _num(int(nbytes))
    return "%s %s" % (_num(size, 1), UNITS[i])


def stat_path(path):
    """Return (total, used, avail) in bytes for path, or None if unavailable."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    # (f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, ...)
    frsize = st[1] or st[0]
    total = st[2] * frsize
    free = st[3] * frsize
    avail = st[4] * frsize
    if total <= 0:
        return None
    return total, total - free, avail


class Main(Activity):
    def __init__(self):
        super().__init__()
        self.volume_list = None
        # Mounting a slot with no card in it fails slowly and noisily, so a
        # failed attempt is remembered and only retried when asked.
        self.sd_mount_failed = False

    def onCreate(self):
        screen = lv.obj()
        screen.set_style_pad_all(10, 0)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_flex_align(
            lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
        )
        screen.set_style_pad_row(10, 0)

        title = lv.label(screen)
        title.set_text("Storage")

        # Volume cards are rebuilt in here on every refresh.
        self.volume_list = lv.obj(screen)
        self.volume_list.set_width(lv.pct(100))
        self.volume_list.set_height(lv.SIZE_CONTENT)
        self.volume_list.set_style_pad_all(0, 0)
        self.volume_list.set_style_pad_row(10, 0)
        self.volume_list.set_style_border_width(0, 0)
        self.volume_list.set_style_bg_opa(lv.OPA.TRANSP, 0)
        self.volume_list.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.volume_list.remove_flag(lv.obj.FLAG.SCROLLABLE)

        button = lv.button(screen)
        button.set_width(lv.pct(60))
        button.add_event_cb(
            lambda e: self.refresh(retry_sd=True), lv.EVENT.CLICKED, None
        )
        button_label = lv.label(button)
        button_label.set_text("Refresh")
        button_label.center()

        self.setContentView(screen)

    def onResume(self, screen):
        super().onResume(screen)
        # Reading the filesystems here rather than in onCreate keeps the work
        # off the app-launch path.
        self.refresh()

    def _sd_probe(self, internal_stats):
        """Stat the SD mount point, ignoring the internal fs showing through.

        /sdcard is an ordinary directory on the internal filesystem until a
        card is mounted over it, and statvfs on it then reports the internal
        filesystem's numbers. Anything identical to internal storage therefore
        means "nothing mounted here".
        """
        stats = stat_path(SD_PATH)
        if stats is None or stats == internal_stats:
            return None
        return stats

    def sd_stats(self, retry, internal_stats):
        """Return the SD card's (total, used, avail), or None."""
        # Probe the mount point directly rather than trusting a single API:
        # if a card is readable there, it does not matter who mounted it or
        # what the framework's bookkeeping currently says.
        stats = self._sd_probe(internal_stats)
        if stats:
            self.sd_mount_failed = False
            return stats

        if SDCardManager is None:
            return None
        if self.sd_mount_failed and not retry:
            return None

        try:
            SDCardManager.mount()
        except Exception:
            pass

        stats = self._sd_probe(internal_stats)
        self.sd_mount_failed = stats is None
        return stats

    def refresh(self, retry_sd=False):
        if self.volume_list is None:
            return

        internal_stats = stat_path(INTERNAL_PATH)
        volumes = [("Internal", INTERNAL_PATH, internal_stats)]

        sd = self.sd_stats(retry_sd, internal_stats)
        volumes.append(("SD card", SD_PATH if sd else None, sd))

        self.volume_list.clean()
        for label, path, stats in volumes:
            self._add_card(label, path, stats)

    def _add_card(self, label, path, stats):
        card = lv.obj(self.volume_list)
        card.set_width(lv.pct(100))
        card.set_height(lv.SIZE_CONTENT)
        card.set_style_pad_all(8, 0)
        card.set_style_pad_row(6, 0)
        card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        card.remove_flag(lv.obj.FLAG.SCROLLABLE)

        heading = lv.label(card)

        if stats is None:
            heading.set_text(label)
            note = lv.label(card)
            note.set_text("Not mounted" if path is None else "Unreadable")
            return

        total, used, avail = stats
        percent = int(used * 100 // total)

        heading.set_text("%s  %s  %d%%" % (label, path, percent))

        bar = lv.bar(card)
        bar.set_width(lv.pct(100))
        bar.set_height(12)
        bar.set_range(0, 100)
        # anim_enable_t is a plain flag; False avoids depending on lv.ANIM,
        # which this LVGL build does not expose.
        bar.set_value(percent, False)

        detail = lv.label(card)
        detail.set_width(lv.pct(100))
        detail.set_text(
            "%s used of %s\n%s free" % (human(used), human(total), human(avail))
        )