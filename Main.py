import os
import base64
import requests
import datetime
import json
import time
from urllib.parse import urlparse, parse_qs
import re
import difflib
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd


from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

client_id = os.getenv('clientID')
client_secret = os.getenv('client_Secret')
youtube_api_key = os.getenv('youtube_api_key')
spotify_user_id = os.getenv('username')
redirect_uri = os.getenv('redirect_uri', 'http://127.0.0.1:8888/callback')

api_service_name = "youtube"
api_version = "v3"

youtube = build(api_service_name, api_version, developerKey=youtube_api_key)

class CreatePlaylist:
    def __init__(self, playlist_url):
        self.playlist_id = self.extract_playlist_id(playlist_url)
        self.token = self.get_token()
        self.user_id = spotify_user_id
        self.youtube = youtube
        self.all_song_info = {}
    
    def extract_playlist_id(self, playlist_url):
        try:
            parsed_url = urlparse(playlist_url)
            query_params = parse_qs(parsed_url.query)
            if 'youtube.com' in parsed_url.netloc:
                playlist_id = query_params['list'][0]
                return playlist_id
        except Exception as e:
            print('Invalid URL: Make sure you have uploaded a youtube link a valid playlist:', str(e))
            return None

    def get_video_ids(self, playlist_id):
        video_ids = []
        next_page_token = None
        
        while True:
            request = self.youtube.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response['items']:
                video_ids.append(item['contentDetails']['videoId'])

            next_page_token = response.get('nextPageToken')
            if next_page_token is None or len(video_ids) >= 150:
                break

        return video_ids

    def clean_title(self, video_title, channel_title="", description=""):
        """
        Works out the artist and song name of a video using only what the youtube api gives us.
        Params:

        video_title: title of the video, eg: "Tinashe - Needs (Official Video)"
        channel_title: name of the channel that uploaded it
        description: description of the video

        Returns:
        (artist, song_name) eg: ("Tinashe", "Needs")
        """
        # auto generated "Topic" videos have clean info in the description:
        # "Provided to YouTube by ...\n\nSong Name · Artist Name · ..."
        provided = re.search(r"Provided to YouTube by [^\n]*\n+([^\n·]+?) · ([^\n·]+)", description)
        if provided:
            return provided.group(2).strip(), provided.group(1).strip()

        title = video_title
        # throw away everything after a "|" eg: "| A COLORS SHOW"
        title = title.split("|")[0]
        # remove brackets that only hold junk words eg: (Official Video) [Lyrics] (4K)
        junk = r"official|videos?|audio|lyrics?|visuali[sz]er|music|mv|m/v|hd|4k|hq|explicit|clip|full|version"
        title = re.sub(rf"[\(\[][^\)\]]*\b({junk})\b[^\)\]]*[\)\]]", "", title, flags=re.IGNORECASE)
        # remove featured artists eg: (feat. X) / ft. X
        title = re.sub(r"[\(\[]?\b(feat|ft)\b\.?[^\)\]]*[\)\]]?", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" -–—")

        # "Artist - Song"
        parts = re.split(r"\s[-–—]\s", title, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip().strip('"')

        # no separator, so the channel name is our best guess for the artist
        artist = re.sub(r"\s*(- Topic|VEVO)$", "", channel_title, flags=re.IGNORECASE).strip()
        return artist, title.strip('"')

    def get_video_details(self, video_ids):
        """
        Get the title, channel and description of all videos with given IDs
        and work out the artist and song name from them.
        Params:

        video_ids: list of video IDs

        Returns:
        Nothing, fills self.all_song_info with the artist, song and spotify uri of each video
        """

        for i in range(0, len(video_ids), 50):  ##Takes all the videos that are present in the playlist
            request = self.youtube.videos().list(
                part="snippet",
                id = ','.join(video_ids[i:i+50])
            )
            response = request.execute()

            for video in response['items']:
                video_title = video["snippet"]["title"]
                youtube_url = "https://www.youtube.com/watch?v={}".format(
                    video["id"])

                artist, song_name = self.clean_title(
                    video_title,
                    video["snippet"].get("channelTitle", ""),
                    video["snippet"].get("description", "")
                )

                spotify_uri, match_name, score = self.search_for_song_uri(song_name, artist)
                self.all_song_info[video_title] = {
                    "youtube_url": youtube_url,
                    "song_name": song_name,
                    "artist": artist,

                    # add the uri, easy to get song to put into playlist
                    "spotify_uri": spotify_uri,
                    "spotify_match": match_name,
                    "match_score": score
                }

    def get_token(self):
        # client credentials can only read, creating a playlist needs the user to log in once
        # (a browser window opens the first time, afterwards the token is cached in .cache)
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="playlist-modify-public playlist-modify-private"
        )
        return auth_manager.get_access_token(as_dict=False)

    def get_auth_header(self):
        return {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}

    def create_playlist(self):
        request_body = json.dumps({
            "name": f"New Playlist: {self.playlist_id}",
            "description": "playlist_url",
            "public": True
        })

        query = "https://api.spotify.com/v1/me/playlists"  # the old /users/{id}/playlists url now returns 403
        response = requests.post(
            query,
            data=request_body,
            headers=self.get_auth_header()   
        )
        if response.status_code not in (200, 201):
            raise Exception(f"Could not create the Spotify playlist. Status code: {response.status_code} {response.text}")
        response_json = response.json()

        return response_json['id']

    def similarity(self, a, b):
        """How alike two strings are, from 0 (nothing) to 1 (identical), ignoring case and punctuation."""
        clean = lambda text: re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()
        return difflib.SequenceMatcher(None, clean(a), clean(b)).ratio()

    def search_for_song_uri(self, song_name, artist, min_score=0.6):
        """
        Searches spotify and returns the closest of the top 5 results.

        Returns:
        (uri, "Song - Artist" that was matched, score) or (None, None, score) if nothing is close enough
        """
        url = "https://api.spotify.com/v1/search"
        headers = self.get_auth_header()
        params = {"q": f"{song_name} {artist}".strip(), "type": "track", "limit": 5}

        # retry if spotify says we are going too fast (429), waiting as long as it asks
        for attempt in range(5):
            result = requests.get(url, headers=headers, params=params)
            if result.status_code != 429:
                break
            wait = int(result.headers.get("Retry-After", 5)) + 1
            print(f"Spotify rate limit hit, waiting {wait}s...")
            time.sleep(wait)
        time.sleep(0.3)  # small pause between searches so we stay under the rate limit

        if result.status_code != 200:
            print(f"Spotify search failed ({result.status_code}) for: {song_name}")
            return None, None, 0
        json_result = result.json().get("tracks", {}).get("items", [])

        # score each result on how close the song name and artist are to what we asked for
        best_track, best_score = None, 0
        for track in json_result:
            song_score = self.similarity(song_name, track["name"])
            if artist:
                artist_score = max(self.similarity(artist, a["name"]) for a in track["artists"])
                score = 0.6 * song_score + 0.4 * artist_score
            else:
                score = song_score
            if score > best_score:
                best_track, best_score = track, score

        if best_track is None or best_score < min_score:
            return None, None, round(best_score, 2)

        match_name = f"{best_track['name']} - {best_track['artists'][0]['name']}"
        return best_track["uri"], match_name, round(best_score, 2)

    def add_song_to_playlist(self):
        video_ids = self.get_video_ids(self.playlist_id)
        self.get_video_details(video_ids)
        
        # Get the playlist id from the create_playlist method
        playlist_id = self.create_playlist()

        # show what was matched, so wrong matches are easy to spot
        for video_title, info in self.all_song_info.items():
            if info["spotify_uri"] is None:
                print(f"NOT FOUND: {video_title}  (searched: {info['song_name']} / {info['artist']}, best score {info['match_score']})")
            else:
                print(f"{info['match_score']:.2f}  {video_title}  ->  {info['spotify_match']}")

        # collect all of uri (skip songs that were not found on spotify)
        uris = [info["spotify_uri"]
                for song, info in self.all_song_info.items()
                if info["spotify_uri"] is not None]

        # Make the request to the Spotify API (it accepts at most 100 songs at a time)
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/items"  # /tracks now returns 403
        headers = self.get_auth_header()
        for i in range(0, len(uris), 100):
            data = json.dumps({"uris": uris[i:i+100]})
            response = requests.post(url, headers=headers, data=data)

            # check for valid response status (spotify answers 201 when songs are added)
            if response.status_code not in (200, 201):
                raise Exception(f"Failed to add songs to playlist. Status code: {response.status_code} {response.text}")

        playlist_link = f"https://open.spotify.com/playlist/{playlist_id}"
        print(f"Successfully added {len(uris)} songs to your new playlist:")
        print(playlist_link)
        return playlist_link

if __name__ == '__main__':
    playlist_url = input("Please input your YouTube playlist URL: ")
    cp=CreatePlaylist(playlist_url)
    cp.add_song_to_playlist()