#!/usr/bin/env python3

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''
try:
    from fusepy import Operations as FuseOperations, FuseOSError, FUSE
except ImportError:
    from fuse import Operations as FuseOperations, FuseOSError, FUSE
import time
import os
import stat
import errno


def sanitize_filename(filename):
    return filename.replace('/', "\u2571")


class CacheControl():
    def __init__(self, ttl):
        self.cache = {'ttl': ttl, 'time': 0}

    def is_cached(self):
        return time.time() - self.cache['time'] < self.cache['ttl']

    def validate_cache(self, ttl=None):
        if ttl != None:
            self.cache['ttl'] = ttl
        self.cache['time'] = time.time()

    def invalidate_cache(self):
        self.cache['time'] = 0


class FS(object):
    def __init__(self, name):
        self.name = name
        self.attr = None

    def get_attr(self):
        return self.attr

    def get_name(self):
        return self.name

    def get_content(self):
        pass


class Directory(FS):

    def __init__(self, name):
        FS.__init__(self, name)
        self.attr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(),
                         st_gid=os.getgid(), st_uid=os.getuid(), st_mode=stat.S_IFDIR | 0o755,
                         st_nlink=2, st_size=4096)
        self.default_content = ['.', '..']
        self.children = []

    def get_children(self):
        return self.children

    def get_content(self):
        return self.default_content + [c.get_name() for c in self.get_children()]


class RootDirectory(Directory):
    def __init__(self):
        Directory.__init__(self, '')


class File(FS):
    def __init__(self, name):
        FS.__init__(self, name)
        self.attr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(),
                         st_gid=os.getgid(), st_uid=os.getuid(), st_mode=stat.S_IFREG | 0o644,
                         st_nlink=1, st_size=8192)


class Tree():
    def __init__(self, root):
        self.children = [root]

    def get_children(self):
        return self.children

    def find_by_path(self, path):
        splited_path = path.rstrip('/').split('/')

        item = self
        for name in splited_path:
            dirs = item.get_children()
            for d in dirs:
                if d.get_name() == name:
                    item = d
                    break
            else:
                raise FuseOSError(errno.ENOENT)

        return item


class Operations(FuseOperations):

    def __init__(self, root):
        FuseOperations.__init__(self)
        self.tree = Tree(root)

    def getattr(self, path, fh=None):
        return self.tree.find_by_path(path).get_attr()

    def readdir(self, path, fh):
        return self.tree.find_by_path(path).get_content()

    def read(self, path, size, offset, fh):
        return self.tree.find_by_path(path).get_content()


def mount(root, mountpoint, **kwargs):
    kwargs.setdefault('nothreads', True)
    kwargs.setdefault('allow_other', True)

    FUSE(Operations(root), mountpoint, **kwargs)

def parse_options(options_s):
    options_d = {}
    for option_s in options_s.split(','):
        option_l = option_s.split('=')
        if len(option_l) == 2:
            options_d[option_l[0]] = option_l[1]
        else:
            options_d[option_l[0]] = True
    return options_d


if __name__ == '__main__':
    import argparse
    import importlib

    parser = argparse.ArgumentParser()
    parser.add_argument('site', type=str, help='Site name or alias')
    parser.add_argument('path', type=str, help='Target path')
    parser.add_argument('-i', '--interactive', help='Mount in interactive mode', action='store_true')
    parser.add_argument('-o', '--options', help='Mount options')
    parser.add_argument('-d', '--daemon', help='Start as daemon', action='store_true')

    sites = {'animevost': 'animevostorg', 'animevostorg': 'animevostorg'}

    arguments = parser.parse_args()
    options = parse_options(arguments.options)
    options.setdefault('fsname', sites[arguments.site])
    options.setdefault('foreground', arguments.interactive)
    options.setdefault('quality', 'hd')

    root = getattr(importlib.import_module(sites[arguments.site]), 'Root')(options['quality'])
    del options['quality']
    mount(root, arguments.path, **options)
