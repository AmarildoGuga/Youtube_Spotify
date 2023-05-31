import os
import base64
import requests
import datetime
from requests import post
import numpy as np
import pandas as pd
from IPython.display import JSON
from urllib.parse import urlparse, parse_qs
import youtube_dl

from googleapiclient.discovery import build

#Environment File
from dotenv import load_dotenv
load_dotenv('/Users/dodo/Library/CloudStorage/OneDrive-JCWResourcing/Development/Projects/Youtube Project/Youtube_Spoitfy/Youtube_Spotify/.env')





##Getting information out of the .env file
client_id = os.getenv('clientID')
client_secret = os.getenv('client_Secret')
youtube_api_key = os.getenv('youtube_api_key')
spotify_user_id = os.getenv('username')


"""Youtube API Verification and Credentials"""
#Documentation file from youtube V3 data pack to get a users youtube data as a list
api_service_name = "youtube"
api_version = "v3"

# Get credentials and create an API client
youtube = build(
    api_service_name, api_version, developerKey=youtube_api_key)


class CreatePlaylist:
    
    def __init__(self, playlist_url):
        self.playlist_url = playlist_url
        self.token = self.get_token()
        self.playlist_id = self.extract_playlist_id(self.playlist_url)
        self.video_ids = self.get_video_ids(youtube, self.playlist_id)
        self.video_data = self.get_video_details(youtube, self.video_ids)
        self.playlist_id_spotify = self.create_playlist()
    
    
    
    
    #playlist_url = 'https://www.youtube.com/watch?v=BBpIV9A1PXc&list=RDBBpIV9A1PXc&start_radio=1&ab_channel=NIKI'
    #print(extract_playlist_id(playlist_url))
        
    def extract_playlist_id(self, playlist_url):
        """
        This function takes a youtube playlist URL and takes
        out the id of the playlist

        Args:
            playlist_url (string): URL
            eg: https://www.youtube.com/watch?v=BBpIV9A1PXc&list=RDBBpIV9A1PXc&start_radio=1&ab_channel=NIKI'

        Returns:
            string: eg: RDBBpIV9A1PXc
        """
        try:
            parsed_url = urlparse(playlist_url)
            query_params = parse_qs(parsed_url.query)
            
            if 'youtube.com' in parsed_url.netloc:
                playlist_id = query_params['list'][0]
                return playlist_id
            
        except Exception as e:
            print('Invalid URL: Make sure you have uploaded a youtube link a valid playlist:', str(e))
            return None   
        
        
        
        
    def get_video_ids(self, youtube, playlist_id):
        """
        Get list of video IDs of all videos in the given playlist
        Params:
        
        youtube: the build object from googleapiclient.discovery
        playlist_id: playlist ID of the channel
        
        Returns:
        List of video IDs of all videos in the playlist
        
        """
        video_ids = []

        request = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults = 50
        )
        response = request.execute()
        
        for item in response['items']:
            video_ids.append(item['contentDetails']['videoId'])
        
        #Youtube API limits you to 50 requests per page - work around 
        next_page_token = response.get('nextPageToken')
        while next_page_token is not None and len(video_ids) < 150: #limit to 150 videos
            request = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults = 50,
                pageToken = next_page_token
            )
            response = request.execute()
            
            for item in response['items']:
                video_ids.append(item['contentDetails']['videoId'])
                
            next_page_token = response.get('nextPageToken')
            
        return video_ids

    def get_video_details(self, youtube, video_ids):
        """
        Get video statistics of all videos with given IDs
        Params:
        
        youtube: the build object from googleapiclient.discovery
        video_ids: list of video IDs
        
        Returns:
        Dataframe with statistics of videos, i.e.:
            'channelTitle', 'title', 'description', 'tags', 'publishedAt'
            'viewCount', 'likeCount', 'favoriteCount', 'commentCount'
            'duration', 'definition', 'caption'
        """
        
        all_video_info = []

        for i in range(0, len(video_ids), 50):  ##Takes all the videos that are present in the playlist
            request = youtube.videos().list(
                part="snippet,contentDetails,statistics",
                id = ','.join(video_ids[i:i+50])
            )
            response = request.execute()

            for video in response['items']:
                video_title = item["snippet"]["title"]
                video_url = 'https://www.youtube.com/watch?v={}'.format(item['id'])
                
                #Use youtube_dl to collect song name & artist
                video = youtube_dl.YoutubeDL({}).extract_info(video_url, download=False)
                song_name = video['track']
                artist = video['artist']
                
                video_info = {}
                video_info['video_title'] = video_title
                video_info['song_name'] = song_name
                video_info['artist'] = artist
                video_info['youtube_url'] = video_url
                video_info['Spotify_uri'] = self.search_for_song_uri(self.get_token, song_name, artist)
                            
                
                all_video_info.append(video_info)
            
        return pd.DataFrame(all_video_info)
    
    
    
    
    
    
    
    def get_token(self):
        """
        This function uses my clientID and client secret encoded using base64 to
        get a spotify token.
        """
        #getting authorisation string from spotify
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode("utf-8")
        auth_base64 = str(base64.b64encode(auth_bytes), "utf-8")

        url = 'https://accounts.spotify.com/api/token'
        method = "POST"
        token_data = {
            "grant_type": "client_credentials"
        }

        token_headers = {
                "Authorization": f"Basic {auth_base64}",
                "Content-Type": "application/x-www-form-urlencoded"
        }


        result = requests.post(url, headers=token_headers, data=token_data)
        valid_request = result.status_code in range(200, 299)
        
        if valid_request:
            now = datetime.datetime.now()
            token_response_data = result.json()
            access_token = token_response_data['access_token']
            expires_in = token_response_data['expires_in'] #seconds
            expires = now + datetime.timedelta(seconds=expires_in)
            return access_token
        else:
            return TypeError('oops token not working')
        
        return access_token

    """token = get_token()
    print(token)"""
    
    
    def get_auth_header(self):
        return {"Authorization": "Bearer " + self.get_token()}
    
    def create_playlist(self):
        """This function creates a playlist on spotify and then returns 
        the id of that playlist so we can add our songs to it.

        Returns:
            id variable from the json file
        """
        request_body = json.dumps({
            "name": f"New Playlist: {playlist_id}",
            "description": "playlist_url",
            "public": True
        })
        
        query = f"https://api.spotify.com/v1/users/{self.user_id}/playlists"
        response = requests.post(
            query,
            data=request_body,
            headers= get_auth_header(token)   
        )
        response_json = response.json()
        
        #return spotify playlist id
        return response_json['id']
    
    def search_for_song_uri(self, song_name, artist):    
        url = "https://api.spotify.com/v1/search"
        headers = self.get_auth_header(token)
        query = f"?q=track%3a{song_name}+artist%3A{artist}&type=artist%2Ctrack"
        query_url = url + query
        
        
        result = requests.get(query_url, headers=headers)
        json_result = json.loads(result.content)["tracks"]["items"]
        if len(json_result) == 0:
            print("No artist or song with this name exists...")
            return None
        
        #returns only the first song on the search query
        uri = json_result[0]["uri"]
        return uri
    
    def add_song_to_playlist(self):
        uris = [song['Spotify_uri'] for song in self.video_data if song['Spotify_uri'] is not None]
        request_data = json.dumps(uris)
        query = f"https://api.spotify.com/v1/playlists/{self.playlist_id_spotify}/tracks"

        response = requests.post(
            query,
            data=request_data,
            headers=self.get_auth_header()
        )
        
        # check for valid response status
        if response.status_code != 200:
            raise Exception(f'something is wrong:' response.status_code)
        
        response_json = response.json()
        return response_json
    
    #Playlist urls:
    #https://www.youtube.com/watch?v=BBpIV9A1PXc&list=RDBBpIV9A1PXc&start_radio=1&ab_channel=NIKI
    #https://www.youtube.com/watch?v=Dyg_ZX2jp3o&list=RDDyg_ZX2jp3o&start_radio=1&ab_channel=88rising
    #User inputs the playlist URL they want
    #Need to write a function that pulls out the ID from the URL

    
if __name__ == '__main__':
    playlist_url = input("Please input your YouTube playlist URL: ")
    cp = CreatePlaylist(playlist_url)
    cp.add_song_to_playlist()