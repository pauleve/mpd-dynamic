# mpd-dynamic - Dynamic playlists for MPD using Spotify and LastFM

This script will auto-complete your MPD playlist using track recommendations from Spotify and LastFM.

## Installation

```
pip install https://github.com/pauleve/mpd-dynamic/archive/main.zip
```

## Configuration

You will need to register your app at Spotify [Development Dashboard](https://developer.spotify.com/dashboard/applications) to get the credentials necessary to make authorized calls (a client id and client secret).

Then, create a file `~/.config/mpd_dynamicrc`:
```cfg
[spotify]
id = xxxx
secret = xxx
# limit: number of results to fetch from spotify to find matching local files (increase if your library is small)
limit = 30
market = FR
# market is optional, see https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2
weight = 2
# at most weight/total_weight of added tracks will come from Spotify

[lastfm]
weight = 1
# at most weight/total_weight of added tracks will come from LastFM

[mpd]
host = localhost
port = 6600
password = music
# password is optional

[playlist]
# threshold: if the remaining number of tracks is less than threshold, it will trigger recommendations
# extend: how many recommended tracks to add when there is less than {threshold} tracks in the playlist
threshold = 10
extend = 3
```

### Artist blacklist

Artists to blacklist have to be specified in the `~/.config/mpd_dynamic-blacklist.txt` file, with one artist per line.
The content of the file is regularly reloaded, so there is no need to restart
the program.

## Usage

Simply launch the command
```
mpd-dynamic
```
Stop with <kbd>Ctrl+c</kbd>

## Acknowledgement

Mainly inspired by https://github.com/bboggess/mpdynamic
