AnimeVost.org file system adapter (FUSE driver)
===============================================

This is my first probe on Python in general and with FUSE in particular, it is not fully workable at the moment.

This is a FUSE file system driver for site animevost.org. Main purpose is to "mount" this site as a part of file system as if it's a file system with anime serials as directories and series as files to make it possible to play movies with any player on any devise without special client. Last step should be sharing this file system via NFS.