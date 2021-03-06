#!/usr/bin/env python
import mpd
import spotipy
import os
import random
import re
import socket

import requests

import logging
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

from appdirs import user_config_dir
import configparser

cfg_file = os.path.join(user_config_dir(), "mpd_dynamicrc")
config = configparser.ConfigParser()
config.read([cfg_file])

THRESHOLD = 10
EXTEND_LIMIT = 3
if "playlist" in config:
    THRESHOLD = config["playlist"].getint("threshold", THRESHOLD)
    EXTEND_LIMIT = config["playlist"].getint("extend", EXTEND_LIMIT)

LOOKUP_WINDOW = EXTEND_LIMIT*10
if "spotify" in config:
    LOOKUP_WINDOW = config["spotify"].getint("limit", LOOKUP_WINDOW)


class ArtistBlacklist(set):
    def __init__(self):
        self.filename = os.path.join(user_config_dir(), "mpd_dynamic-blacklist.txt")
        self.reload()

    def __contains__(self, track):
        return super().__contains__(track.artist)

    def reload(self):
        self.clear()
        try:
            with open(self.filename) as fp:
                self.update([l.strip() for l in fp])
        except FileNotFoundError:
            pass

class Track(object):
    def __init__(self, title, artist, album, id=None):
        self.title = title
        self.artist = artist
        self.album = album
        self.id = id
        self.suggested_by = None

    def __str__(self):
        extra = f" [suggested by {self.suggested_by}]" \
                    if self.suggested_by else ""
        return f"{self.artist} - {self.title} ({self.album}){extra}"
    def __repr__(self):
        return f"{self.artist} - {self.title} ({self.album})"

    @classmethod
    def from_spotify(celf, track):
        return celf(track["name"],
                track["artists"][0]["name"],
                track["album"]["name"], track["id"])
    @classmethod
    def from_mpd(celf, track):
        return celf(track["title"], track["artist"], track.get("album"),
                    track["file"])

class MPDProxy(object):
    def __init__(self):
        self.connect()

    def connect(self):
        self.mpd = mpd.MPDClient()
        self.mpd.timeout = 10
        self.mpd.idletimeout = None
        host = "localhost"
        port = 6600
        password = None
        if "mpd" in config:
            host = config["mpd"].get("host", host)
            port = config["mpd"].getint("port", port)
            password = config["mpd"].get("password", "")
        self.mpd.connect(host, port)
        if password:
            self.mpd.password(password)

    def __del__(self):
        try:
            self.mpd.close()
            self.mpd.disconnect()
        except mpd.base.ConnectionError:
            pass

    def auto_retry(func):
        def do(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except socket.timeout:
                self.connect()
                return func(self, *args, **kwargs)
        return do

    @auto_retry
    def currentsong(self):
        track = self.mpd.currentsong()
        if track:
            return Track.from_mpd(track)

    @auto_retry
    def count_songs_remaining(self):
        """
        Calculates the number of songs remanining on current playlist
        """
        status = self.mpd.status()
        try:
            i = int(status.get('song', 0))
        except ValueError:
            return THRESHOLD # wait
        return int(status['playlistlength']) - i

    def add_track(self, track):
        logging.info(f"Adding {track}")
        self.mpd.add(track.id)

    def matching_track(self, track):
        matches = self.mpd.search("title", track.title, "artist", track.artist)
        matches = list(map(Track.from_mpd, matches))
        if matches:
            matches0 = [t for t in matches if t.album == track.album]
            if matches0:
                maches = matches0
            return random.choice(matches)

    @auto_retry
    def random_track(self, artist):
        matches = self.mpd.search("artist", artist)
        if matches:
            return Track.from_mpd(random.choice(matches))

class UnboundedHistory(set):
    def _view_track(self, track):
        return (track.artist, track.title)
    def add_track(self, track):
        self.add(self._view_track(track))
    def has_track(self, track):
        return self._view_track(track) in self

class SpotifyRecommendations(object):
    def __init__(self, history, blacklist):
        SPOTIFY_ID = config["spotify"]["id"]
        SPOTIFY_SECRET = config["spotify"]["secret"]
        creds = spotipy.SpotifyClientCredentials(SPOTIFY_ID, SPOTIFY_SECRET)
        self.spotify = spotipy.Spotify(client_credentials_manager=creds)
        self.history = history
        self.blacklist = blacklist
        self.market = config["spotify"].get("market")

    def resolve(self, track):
        artist = track.artist.replace("-"," ")
        title = track.title.replace("-"," ")
        simple_title = re.sub(r"\(.*\)", "", title).strip()
        queries = [f"artist:\"{artist}\" {title}",
                f"{artist} {title}"]
        if simple_title != title:
            queries.append(f"{artist} {simple_title}")
        for query in queries:
            results = self.spotify.search(q=query, type='track', limit=1,
                        market=self.market)
            results = results['tracks']['items']
            if results:
                break
        if not results:
            logging.warn(f"No spotify track for {track} (query was: {query})")
            return
        logging.debug(f"{track} is {results[0]}")
        return results[0]['id']

    def similar(self, tracks, lib, limit=EXTEND_LIMIT):
        ids = [i for i in map(self.resolve, tracks) if i]
        if not ids:
            return []
        recs = self.spotify.recommendations(seed_tracks=ids,
                    limit=LOOKUP_WINDOW)['tracks']
        recs = list(map(Track.from_spotify, recs))
        random.shuffle(recs)

        selected = []

        def valid_pick(t):
            return not self.history.has_track(t)\
                    and not t in self.blacklist

        def pick(track, mtrack):
            mtrack.suggested_by = "Spotify"
            selected.append(mtrack)
            #self.history.add(track.id) # .insert(0, track.id)
            self.history.add_track(track)
            return len(selected) == limit

        # 1. prefer new specific tracks
        for track in recs:
            mtrack = lib.matching_track(track)
            if mtrack and valid_pick(mtrack):
                if pick(track, mtrack):
                    break
            else:
                logging.info(f"No local track for {track}")
        if selected:
            return selected

        logging.info(f"No local tracks matching recommendations for {tracks}, falling back to artists")

        # 2. fallback to artists
        for track in recs:
            mtrack = lib.random_track(track.artist)
            if mtrack and valid_pick(mtrack):
                if pick(track, mtrack):
                    break

        if not selected:
            logging.warn(f"No local match for recommendations for {tracks}")

        return selected

class LastFMRecommendations(object):
    def __init__(self, history, blacklist):
        self.history = history
        self.blacklist = blacklist

        LASTFM_API_KEY = "5a854b839b10f8d46e630e8287c2299b";
        self.session = requests.Session()
        self.session.params["api_key"] = LASTFM_API_KEY

    def similar(self, tracks, lib, limit=EXTEND_LIMIT):
        seed_artist = tracks[0].artist
        ret = self.session.get("https://ws.audioscrobbler.com/2.0", params={
            "method": "artist.getSimilar",
            "artist": seed_artist,
            "format": "json",
            "limit": 50})
        ret = ret.json()
        if "similarartists" not in ret:
            return []
        artists = [d["name"] for d in ret["similarartists"]["artist"]]
        selected = []
        for _ in range(limit):
            random.shuffle(artists)
            for artist in artists:
                for i in range(5):
                    track = lib.random_track(artist)
                    if not track:
                        logging.info(f"No local artist {artist}")
                        break
                    if track in self.blacklist:
                        continue
                    if not self.history.has_track(track):
                        self.history.add_track(track)
                        track.suggested_by = "LastFM"
                        selected.append(track)
                        if len(selected) == limit:
                            return selected
                        break
        return selected


def get_probs():
    weight = {"spotify": 2, "lastfm": 1}
    for key in weight:
        if key in config:
            weight[key] = config[key].get("weight", weight[key])
    total = sum(weight.values())
    return {key: val/total for key, val in weight.items()}

def main():
    random.seed()
    lib = MPDProxy()
    blacklist = ArtistBlacklist()
    hist = UnboundedHistory()
    for track in lib.mpd.playlistinfo():
        hist.add_track(Track.from_mpd(track))
    feed1 = SpotifyRecommendations(hist, blacklist)
    feed2 = LastFMRecommendations(hist, blacklist)
    probs = get_probs()
    try:
        while True:
            remaining = lib.count_songs_remaining()
            if remaining < THRESHOLD:
                tracks = [lib.currentsong()]
                if None in tracks:
                    continue
                extend_by = max(THRESHOLD-remaining, EXTEND_LIMIT)
                blacklist.reload()
                selected = []
                limit = round(extend_by * probs["spotify"] + 0.5)
                if limit > 0:
                    selected = feed1.similar(tracks, lib, limit=limit)
                limit = extend_by-len(selected)
                if limit > 0:
                    selected += feed2.similar(tracks, lib, limit=limit)
                random.shuffle(selected)
                for track in selected:
                    lib.add_track(track)
            try:
                lib.mpd.idle('playlist', 'player')
            except mpd.base.ConnectionError:
                pass
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
