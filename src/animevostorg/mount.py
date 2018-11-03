#!/usr/bin/python3
'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''
from __future__ import with_statement

from bs4 import BeautifulSoup
import requests
import os
import sys
import errno
import time
import string
import stat
import json

from fuse import FUSE, FuseOSError, Operations
from pycparser.c_ast import Switch


def sanitize_filename(s):
    #     valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    #     filename = ''.join(c for c in s if c in valid_chars)
    filename = s.replace('/', "\u2571")
    return filename


class Animevost(Operations):

    def __init__(self):
        self.series = dict()
        self.site_url = 'http://animevost.org'
        self.api_url = 'https://api.animevost.org/animevost/api/v0.2/playlist'
        self.dirs = {
            'Latest': self.latest_dir(),
            'By update': ['1 Monday', '2 Tuesday', '3 Wednesday', "4 Thursday",
                          "5 Friday", "6 Saturday", "7 Sunday", '8 Unstable'],
            'By name': list(string.ascii_uppercase)
        }
        self.fileattr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(),
                            st_gid=os.getgid(), st_uid=os.getuid(), st_mode=stat.S_IFREG|0o644,
                            st_nlink=0, st_size=4096)
        self.dirattr = dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(),
                            st_gid=os.getgid(), st_uid=os.getuid(), st_mode=stat.S_IFDIR|0o755,
                            st_nlink=2, st_size=4096)

    def readdir(self, path, fh):
        print("path %s; handler %s" % (path, fh))
        for item in Operations.readdir(self, path, fh):
            yield item
        for item in self.read_path(path, fh):
            yield item

    def read(self, path, size, offset, fh):
        pass

    def getattr(self, path, fh=None):
        path = path.split('/').pop()
        return self.dirattr

    def latest_dir(self):
        page = requests.get(self.site_url)
        soup = BeautifulSoup(page.text, 'html.parser')
        last_page = max([int(a.text) for a in soup.find(
            attrs={"class": "block_4"}).findAll('a')])
        return ["%03d" % page for page in range(1, ++last_page)]

    def read_path(self, path, fh):
        path = path.split('/').pop()
        if len(path) == 0:
            return self.dirs.keys()
        if path in self.dirs:
            return self.dirs[path]
        if path in self.dirs['Latest']:
            return self.read_latest(path, fh)
        if path in self.dirs['By update']:
            return self.read_update(path, fh)
        if path in self.dirs['By name']:
            return self.read_name(path, fh)
        if path in self.series:
            return self.read_series(path, fh)
        return []

    def read_latest(self, page, fh):
        page = requests.get(self.site_url + "/page/%d" % int(page))
        soup = BeautifulSoup(page.text, 'html.parser')
        for div in soup(attrs={"class": "shortstoryHead"}):
            series = sanitize_filename(div.a.text)
            self.series[series] = div.a.get('href').regex()
            yield series

    def read_update(self, day, fh):
        pass

    def read_name(self, name, fh):
        pass

    def read_series(self, name, fh):
        page = requests.post(self.api_url, {'titleid' : self.series[name]}, None)
        for item in json.loads(page):
            yield (item.name, self.fileattr, 0)


def mount(mountpoint):
    FUSE(Animevost(), mountpoint, nothreads=True, foreground=True)


if __name__ == '__main__':
    mount(sys.argv[1])
