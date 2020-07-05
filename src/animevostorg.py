#!/usr/bin/env python3
try:
    from fusepy import Operations as FuseOperations, FuseOSError, FUSE
except ImportError:
    from fuse import Operations as FuseOperations, FuseOSError, FUSE
from argparse import ArgumentParser
from typing import Iterable, List, Iterator
from cachetools import cached, TTLCache
import errno
import os
import stat
import time
import json
import requests
import yaml

'''
Created on Oct 30, 2018

@author: Dmytro Dubrovny <dubrovnyd@gmail.com>
'''


class File:
    PURITY_SIMPLE = 'simple'
    PURITY_LATIN = 'latin'
    PURITY_EXTRA = 'extra'

    def __init__(self, name: str, purity=None, content: str = ''):
        purity = purity or self.PURITY_SIMPLE
        symbols = {
            self.PURITY_SIMPLE: (u"/", "\u2571"),
            self.PURITY_LATIN: (u"абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ/",
                                u"abvgdeejzijklmnoprstufhzcss_y_euaABVGDEEJZIJKLMNOPRSTUFHZCSS_Y_EUA\u2571"),
            self.PURITY_EXTRA: (u"абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ?/",
                                u"abvgdeejzijklmnoprstufhzcss_y_euaABVGDEEJZIJKLMNOPRSTUFHZCSS_Y_EUA_\u2571")
        }
        self.__translation = {ord(a): ord(b) for a, b in zip(*symbols[purity])}
        self.__name = name
        self.__content = content

    def __str__(self) -> str:
        return self.__name.translate(self.__translation)

    @property
    def attr(self):
        return dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(), st_gid=os.getgid(),
                    st_uid=os.getuid(), st_mode=stat.S_IFREG | 0o444, st_nlink=1,
                    st_size=len(self.content))

    @property
    def content(self) -> bytes:
        return self.__content.encode()

    def find(self, path: str) -> 'File':
        if path == '':
            return self
        else:
            raise FuseOSError(errno.ENOTDIR)

    @staticmethod
    def purities():
        return File.PURITY_SIMPLE, File.PURITY_LATIN, File.PURITY_EXTRA


class Directory(File):

    def __init__(self, name: str, purity=None, content: Iterable[File] = ()):
        File.__init__(self, name, purity)
        self.__content = content
        self.__defaults = ['.', '..']

    def __iter__(self):
        return iter(self.__content)

    @property
    def attr(self):
        return dict(st_atime=time.time(), st_ctime=time.time(), st_mtime=time.time(), st_gid=os.getgid(),
                    st_uid=os.getuid(), st_mode=stat.S_IFDIR | 0o555, st_nlink=1, st_size=4096)

    @property
    def content(self) -> List[str]:
        return self.__defaults + [str(item) for item in self]

    def find(self, path: str) -> File:
        if path == '':
            return self

        split = path.split(os.sep)
        name = split.pop(0)
        for item in self:
            if str(item) == name:
                item = item.find(os.sep.join(split))
                return item

        raise FuseOSError(errno.ENOENT)


class PlaylistItem:

    def __init__(self, title: str, path: str, duration: int = -1):
        self.__title = title
        self.__path = path
        self.__duration = duration

    def __str__(self) -> str:
        if len(self.path):
            return '#EXTINF:{:d}, {:s}\n{:s}\n'.format(self.duration, self.title, self.path)
        else:
            return '\n'

    @property
    def title(self) -> str:
        return self.__title

    @property
    def path(self) -> str:
        return self.__path

    @property
    def duration(self) -> int:
        return self.__duration


class Playlist(File):

    def __init__(self, name: str, purity: str = File.PURITY_SIMPLE, items: Iterable[PlaylistItem] = ()):
        File.__init__(self, '{:s}.m3u8'.format(name), purity)
        self.__items = items

    def __iter__(self):
        return iter(self.__items)

    @property
    def content(self) -> bytes:
        return ('#EXTM3U\n' + '\n'.join(str(item) for item in self)).encode()


class Operations(FuseOperations):

    def __init__(self, root: Directory):
        FuseOperations.__init__(self)
        self.root = root

    def getattr(self, path: str, fh=None):
        return self.root.find(path.lstrip(os.sep)).attr

    def readdir(self, path: str, fh):
        return self.root.find(path.lstrip(os.sep)).content

    def read(self, path: str, size, offset, fh):
        return self.root.find(path.lstrip(os.sep)).content


class GetTokenError(Exception):

    def __init__(self, message: str = ''):
        self.__message = message

    def __str__(self) -> str:
        return self.__message


class TitleFinder:
    FIELD_GENRE = 'gen'
    FIELD_NAME = 'name'
    FIELD_CATEGORY = 'cat'
    FIELD_YEAR = 'year'

    def __init__(self, config: 'Configuration', **params):
        self.__config = config
        self.__params = params

    def __iter__(self) -> Iterator[File]:
        return iter(self.__search())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __search(self) -> List[File]:
        page = requests.post('{:s}/search'.format(self.__config.api), self.__params)
        series = json.loads(page.text)
        series.setdefault('data', [])
        titles = [Title('{:02d} {:s}'.format(i, s['title']), s['id'], self.__config) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class Episode(PlaylistItem):

    def __init__(self, title: str, urls: dict, config: 'Configuration'):
        PlaylistItem.__init__(self, title, '')
        self.__urls = urls
        self.__config = config

    def __lt__(self, other: 'Episode') -> bool:
        self_split = self.title.split(' ')[0]
        other_split = other.title.split(' ')[0]
        try:
            self_num = int(self_split)
        except ValueError:
            try:
                int(other_split)
            except ValueError:
                return self.title < other.title
            return False
        try:
            other_num = int(other_split)
        except ValueError:
            return True
        return int(self_num) < int(other_num)

    @property
    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def path(self) -> str:
        if self.__config.quality in self.__urls and requests.head(self.__urls[self.__config.quality]).ok:
            return self.__urls[self.__config.quality]
        else:
            for quality in Configuration.qualities():
                if quality in self.__urls and requests.head(self.__urls[quality]).ok:
                    return self.__urls[quality]
        return ''


class Title(Directory):
    GROUP_SINGLE = 'single'
    GROUP_ALL = 'all'
    GROUP_EACH_TO_LAST = 'each-to-last'

    def __init__(self, name: str, title_id: int, config: 'Configuration'):
        Directory.__init__(self, name, config.purity)
        self.__title_id = title_id
        self.__config = config

    def __iter__(self):
        return iter(self.__items())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __items(self) -> List[File]:
        page = requests.post('{:s}/playlist'.format(self.__config.api), {'id': self.__title_id}, None)
        series_data = json.loads(page.text)
        series = []
        for episode_data in series_data:
            series.append(Episode(episode_data['name'], episode_data, self.__config))
        sorted_series = sorted(series)
        total = len(sorted_series)
        if total < self.__config.limit * 1.2:
            items = self.__create_playlists(sorted_series)
        else:
            items = []
            for i in range(0, total, self.__config.limit):
                chunk = sorted_series[i:i + self.__config.limit]
                if self.__config.group == Title.GROUP_ALL:
                    items.append(
                        Playlist('{:03d}-{:03d}'.format(i + 1, min(i + self.__config.limit, total)),
                                 self.__config.purity, chunk))
                else:
                    items.append(
                        Directory('{:03d}-{:03d}'.format(i + 1, min(i + self.__config.limit, total)),
                                  self.__config.purity, self.__create_playlists(chunk)))
        return items

    def __create_playlists(self, items: Iterator[PlaylistItem]) -> Iterator[Playlist]:
        if self.__config.group == self.GROUP_EACH_TO_LAST:
            for last in items:
                pass
            return [
                Playlist('{:s} - {:s}'.format(item.title, last.title), self.__config.purity, items[n:]) for n, item in
                enumerate(items)]
        if self.__config.group == self.GROUP_SINGLE:
            return [Playlist(item.title, self.__config.purity, [item]) for item in items]

    @staticmethod
    def grouping():
        return Title.GROUP_ALL, Title.GROUP_SINGLE, Title.GROUP_EACH_TO_LAST


class Page(Directory):

    def __init__(self, name: str, number: int, config: 'Configuration', limit: int = 99):
        Directory.__init__(self, name, config.purity)
        self.__number = number
        self.__config = config
        self.__limit = limit

    def __iter__(self) -> Iterator[File]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[File]:
        page = requests.get(
            '{:s}/last?page={:d}&quantity={:d}'.format(self.__config.api, self.__number, self.__limit))
        series = json.loads(page.text)
        titles = [Title('{:02d} {:s}'.format(i, s['title']), s['id'], self.__config) for i, s in
                  enumerate(series['data'], start=1)]
        return titles


class Search(Directory):

    def __init__(self, name: str, field: str, config: 'Configuration'):
        Directory.__init__(self, name, config.purity)
        self.__history = dict()
        self.__field = field
        self.__config = config

    def __iter__(self) -> Iterator[File]:
        return iter(self.__history.values())

    def find(self, path: str) -> 'File':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        search_query = path_listed.pop(0)
        if search_query not in self.__history:
            search_title = TitleFinder(self.__config, **{self.__field: search_query})
            self.__history[search_query] = Directory(search_query, self.__config.purity, search_title)
        deeper_path = os.sep.join(path_listed)
        return self.__history[search_query].find(deeper_path)


class Genres(Directory):

    def __init__(self, name: str, config: 'Configuration'):
        Directory.__init__(self, name, config.purity)
        self.__items = dict()
        self.__config = config

    def __iter__(self) -> Iterator[File]:
        return iter(self.__genres())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __genres(self):
        page = requests.get('{:s}/genres'.format(self.__config.api))
        data = json.loads(page.text)
        return [genre for genre in data.values()]

    def find(self, path: str) -> 'File':
        if path == '':
            return self

        path_listed = path.split(os.sep)
        genre = path_listed.pop(0)
        if genre not in self.__content:
            raise FuseOSError(errno.ENOENT)

        if genre not in self.__items:
            self.__items[genre] = Directory(genre, self.__config.purity,
                                            TitleFinder(self.__config, **{TitleFinder.FIELD_GENRE: genre}))
        deeper_path = os.sep.join(path_listed)
        return self.__items[genre].find(deeper_path)


class Favorites(Directory):

    def __init__(self, name: str, config: 'Configuration'):
        Directory.__init__(self, name, config.purity)
        self.__config = config

    def __iter__(self) -> Iterator[File]:
        return iter(self.__titles())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __titles(self) -> List[File]:
        try:
            token = self.__config.token
        except GetTokenError as err:
            return [File('error.txt', str(err))]
        else:
            page = requests.post('{:s}/favorites'.format(self.__config.api), {'token': token})
            series = json.loads(page.text)
            titles = [Title('{:02d} {:s}'.format(i, s['title']), s['id'], self.__config) for i, s in
                      enumerate(series['data'], start=1)]
            return titles


class All(Directory):

    def __init__(self, name: str, config: 'Configuration', limit: int = 99):
        Directory.__init__(self, name, config.purity)
        self.__config = config
        self.__limit = limit

    def __iter__(self) -> Iterator[File]:
        return iter(self.__pages())

    @cached(cache=TTLCache(maxsize=1024, ttl=3000))
    def __pages(self) -> List[File]:
        page = requests.get('{:s}/last?page=1&quantity={:d}'.format(self.__config.api, self.__limit))
        series = json.loads(page.text)
        if len(series['data']) < self.__limit:
            self.__limit = len(series['data'])
        last_page = series['state']['count'] // self.__limit + 1
        pages = [Page('{:03d}'.format(page), page, self.__config, self.__limit) for page in range(1, last_page + 1)]
        return pages


class Root(Directory):

    def __init__(self, config: 'Configuration'):
        directories = [
            Page('latest', 1, config),
            All('all', config),
            Genres('genres', config),
            Directory('search', config.purity, [
                Search('by-name', TitleFinder.FIELD_NAME, config),
                Search('by-category', TitleFinder.FIELD_CATEGORY, config),
                Search('by-year', TitleFinder.FIELD_YEAR, config)
            ]),
            Favorites('favorites', config)
        ]
        Directory.__init__(self, '', config.purity, directories)


class Configuration:
    QUALITY_SD = 'std'
    QUALITY_HD = 'hd'

    def __init__(self, api: str = None, quality: str = None, purity: str = File.PURITY_SIMPLE,
                 group: str = Title.GROUP_EACH_TO_LAST, limit: int = None, username: str = None, password: str = None):
        self.__group = group
        self.__purity = purity
        self.__username = username
        self.__password = password
        self.__api = api or 'https://api.animetop.info/v1'
        self.__quality = quality or self.QUALITY_HD
        self.__limit = limit or 40

    @property
    def limit(self) -> int:
        return self.__limit

    @property
    def quality(self):
        return self.__quality

    @property
    def api(self) -> str:
        return self.__api

    @property
    def purity(self) -> str:
        return self.__purity

    @property
    def group(self) -> str:
        return self.__group

    @property
    @cached(cache=TTLCache(maxsize=128, ttl=30000))
    def token(self):
        if self.__username is None or self.__password is None:
            raise GetTokenError("Username or password is not configured")
        page = requests.post('{:s}/gettoken'.format(self.api), {'user': self.__username, 'pass': self.__password})
        data = json.loads(page.text)
        if data['status'] == 'ok':
            return data['token']
        raise GetTokenError(data['error'])

    @staticmethod
    def qualities() -> List[str]:
        return [Configuration.QUALITY_SD, Configuration.QUALITY_HD]


def mount(root: Directory, mountpoint: str, **kwargs):
    kwargs.setdefault('fsname', 'www-fuse')
    kwargs.setdefault('nothreads', True)
    if not os.geteuid():
        kwargs.setdefault('allow_other', True)
    FUSE(Operations(root), mountpoint, **kwargs)


if __name__ == '__main__':
    parser: ArgumentParser = ArgumentParser()
    parser.add_argument('-i', '--interactive', help='interactive mode', action='store_true')
    parser.add_argument('-o', '--options', help='mount options', default='')
    parser.add_argument('quality', type=str, help='video quality', choices=Configuration.qualities())
    parser.add_argument('path', type=str, help='target path')

    parser.add_argument('-c', '--config', help='path to configuration file', default='~/.animevost.yaml')
    parser.add_argument('-a', '--api', help='API URL', default='https://api.animetop.info/v1')
    parser.add_argument('-l', '--limit', help='items per directory limit', default=40)
    parser.add_argument('-u', '--username', help='login', default=None)
    parser.add_argument('-p', '--password', help='password', default=None)
    parser.add_argument('-g', '--group', help='group episodes in playlist', default=Title.GROUP_EACH_TO_LAST,
                        choices=Title.grouping())
    parser.add_argument('-s', '--sanitize', help='sanitizer purity', default=File.PURITY_SIMPLE,
                        choices=File.purities())

    arguments = parser.parse_args()
    options = {}
    for option in arguments.options.split(','):
        try:
            (name, value) = option.split('=')
        except ValueError:
            (name, value) = option, True
        options[name] = value
    options.setdefault('foreground', arguments.interactive)
    options.setdefault('fsname', 'animevostorg-{:s}-fuse'.format(arguments.quality))
    try:
        configfile = os.path.expanduser(options.setdefault('config', arguments.config))
        with open(configfile, "r") as stream:
            config = yaml.load(stream, Loader=yaml.BaseLoader)
    except FileNotFoundError:
        config = dict()
    finally:
        del options['config']

    configuration = Configuration(
        username=config.get('username', False) or arguments.username,
        password=config.get('password', False) or arguments.password,
        quality=config.get('quality', False) or arguments.quality,
        purity=config.get('sanitize', False) or arguments.sanitize,
        group=config.get('group', False) or arguments.group,
        limit=config.get('limit', False) or arguments.limit,
        api=config.get('api', False) or arguments.api
    )

    mount(Root(configuration), arguments.path, **options)
