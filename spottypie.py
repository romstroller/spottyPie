import os
import sys
import json
import time
import keyring
import requests
import traceback
import numpy as np
import pandas as pd
from OsOps import Ops
from spotipy import client, util
from collections import namedtuple, Counter


def fetch_credentials():
    ''' supply auth creds from stored in win cred mgr '''
    user_id, sp_cid, sp_sec = ( 
        keyring.get_password( service, "" )
        for service in [
            "spottyPie_user_id",
            "spottyPie_clientID", 
            "spottyPie_clientSecret"] )

    if None in [user_id, sp_cid, sp_sec]: print( "Credential not set locally" )
    else: return user_id, sp_cid, sp_sec

def getAuthResponse():
    # standard API authenticate (not used)
    try: return (
        requests.post( 'https://accounts.spotify.com/api/token', 
            { 'grant_type': 'client_credentials',
                'client_id': sp_cid,
                'client_secret': sp_sec, }) )
    except Exception as exc: print( 
        f"\n[ ERRR ] {exc.__class__}"
        f"\n[ DSTR ] {exc.__doc__}"
        f"\n[ CTXT ] {exc.__context__}"
        f"\n{ '='*79 }"
        f"\n\n{traceback.format_exc()}" )

def auth_SpotPy( user_id, sp_cid, sp_sec ):
    # get authenticated spotipy object
    token = util.prompt_for_user_token(
        username= user_id, 
        scope= " ".join( [
            "playlist-read-private",
            "playlist-modify-private",
            "user-library-modify",
            "user-read-private" ]),
        client_id= sp_cid, 
        client_secret= sp_sec, 
        redirect_uri = "http://example.com/")

    return client.Spotify(token)

def createNewPL( pl_name="New_PL", stamp=True, ):
    try: return spot.user_playlist_create( 
        user= user_id, 
        name= f"{pl_name}_{ops.dtStamp()}" if stamp else pl_name, 
        public=False )
    except Exception as e: return f"EXC createNewPL:\n{type(e).__name__}\n{e}"

def albsFromPList( pl_id ):
    track_list = spot.user_playlist_tracks( user=user_id, playlist_id=pl_id, )
    return { i : {
        "alb_id" : item['track']['album']['id'], 
        "tracks" : item['track']['album']['total_tracks'],
        "dct" : item, } 
        for i, item in enumerate( track_list['items']) }

def getAllTrackIDs( listDict ):
    Alb = namedtuple( "Alb", [ "alb_id", "siz", "dct" ] )
    albsSorted = sorted( [ 
        Alb( d["alb_id"], d['tracks'], d["dct"] )
        for _, d in listDict.items() ],
        key = lambda el: el.siz, reverse=True )
    return [ item['id']
        for alb in albsSorted
        for item in spot.album_tracks( alb.alb_id )['items'] ]

def addTracksByID( idList, destination ):
    def yieldSegments(li, size):
        for i in range(0, len(li), size): yield li[ i:i + size ]
    for seg in yieldSegments(idList, 100):  # max 100
        spot.user_playlist_add_tracks(
            user_id, 
            playlist_id=destination, 
            tracks=seg)

def maximizeList( from_pl_id, new_pl_pref ):
    print( f"Collecting albums from tracks in {from_pl_id}" )
    created_pl = createNewPL( pl_name=new_pl_pref )
    tracklist_dct = albsFromPList( from_pl_id )
    allTrackIDs = getAllTrackIDs( tracklist_dct )
    addTracksByID( allTrackIDs, created_pl['id'] )
    print( f"Playlist with pref {new_pl_pref} created" )

def get_all_pl_tracks( user_id, pl_id):
    rq_dct = spot.user_playlist_tracks( user_id, pl_id )
    tracks = rq_dct['items']
    while rq_dct['next']:
        rq_dct = spot.next(rq_dct)
        tracks.extend(rq_dct['items'])
    return tracks

def get_bins(posits, count, is_reverse): return (
    np.array_split( (posits[::-1] if is_reverse else posits ), count) )
    
def distance_shuffle( input ):
    
    counted = { val : count for val, count in Counter( input ).most_common() }
    length = len(input)
    posits = np.arange( 1, length+1 )
    output = { i : None for i in posits }
    
    is_reverse = False
    for val, count in counted.items():
        for bin in get_bins(posits, count, is_reverse):
            for pos in bin:
                if output[pos]: continue 
                else:
                    output[pos] = val
                    break
                
        is_reverse = not is_reverse # changes direction of bin split-add
    
    return output

def distance_shuffle_playlist(pl_id):
    pl = spot.playlist(pl_id)
    print( f"shuffling {pl['name']} to new list" )
    track_dct = get_all_pl_tracks( user_id, pl_id)

    in_list = [ item["track"]["album"]["id"] for item in track_dct ]
    group_dct = { group_id : [] for group_id in in_list }

    for group_id, group_list in group_dct.items():
        group_list.extend( item["track"]["id"] for item in track_dct 
            if item["track"]["album"]["id"] == group_id )
            
    shuffle = distance_shuffle( in_list )

    out = [ 0 for i in range(len(track_dct)) ]
    for pos, group_id in shuffle.items(): out[pos-1] = group_dct[group_id].pop()

    if ( set([item["track"]["id"] for item in track_dct ]) - set(out) 
        ) or ( len(in_list) != len(out) ): print("somethin ain't right")

    created_pl = createNewPL( pl_name=f"{pl['name']}_shfl" )
    addTracksByID( out, created_pl['id'] )
    print( "completed maxdistance-shuffle" )

def getPlaylists( asDict=False ):
    '''folder structure not available through API as at 221224'''
    incrmt = 50  # max 50
    offset = 0
    plistsDct = {}
    while True:
        newItemDcts = spot.current_user_playlists( incrmt, offset)["items"]
        plistsDct.update( { iDct["id"]: iDct for iDct in newItemDcts } )
        if len(newItemDcts) < incrmt: 
            return pd.DataFrame( plistsDct ).T if not asDict else plistsDct
        else: offset += incrmt

def getTracks( id ):
    '''unused alternative to get_all_pl_tracks, may not complete list'''
    incrmt = 100  # max 100
    offset = 0
    tracks = {}
    while True:
        items = spot.user_playlist_tracks( 
            user=user_id, playlist_id=id, limit=incrmt, offset=offset )["items"]
        tracks.update( { i["track"]["id"]: i for i in items } )
        if len(items) < incrmt: return tracks
        else: offset += incrmt

def get_library( asPandas = False, store = False ):
    ''' if not asDict, returns pandas dataframe
        if not store, returns '''
    
    playlistData = getPlaylists( asDict=not asPandas )
    
    if asPandas: 
        playlistData["tracklist"] = playlistData["id"].apply( 
            lambda id: get_all_pl_tracks( id ) )
    else:
        for id, dct in playlistData.items(): 
            dct["tracks"].update({ "list": getTracks( id )})
    
    print( f"collected library { 'as pd' if asPandas else 'as dict' }, {store=}" )
    if store: ops.storePKL( playlistData, "playlistData", os.getcwd() )
    else: return playlistData

def latestNEps( pl_id, n=3 ):
    tracks = get_all_pl_tracks( user_id, pl_id, )

    showIDs = []

    for track in tracks:
        track_dict = track['track']
        if track_dict: 
            for artist in track_dict["artists"]:
                if artist["type"]=="show": showIDs.append( artist['id'] )
        else:
            print( f"No TRACK DICT: {track}" )

    epIDs = []
    for showID in showIDs:
        show_items = spot.show_episodes(showID)['items']
        eps_recent = sorted( [ ( item["release_date"], item["id"] )
            for item in show_items ], key= lambda i: i[0], reverse=True )
        epIDs.extend( f'spotify:episode:{id}' for _, id in eps_recent[:n] )
        
    return epIDs
    
def getLatestEpsFromPodTList( from_pl_id = "2PFeIO0B0DtenFmGKbzYvg", n=3 ):
    new_pCasts_PL = createNewPL( pl_name="PCST" )
    epIDs = latestNEps( from_pl_id, n )
    addTracksByID( epIDs, new_pCasts_PL['id'] )
    print( f"completed collect latest {n} eps from {from_pl_id}" )

def output_help():
    print( "\nCommands are:")
    indnt = '    '
    for k, v in cmdLib.items(): 
        print( f"\n{indnt}[ {k} ]" )
        for line in v['desc']:
            print( f"{indnt}{line}" )
    print()

cmdLib = {
    
    "maxlist" : { 
        
        "func" : lambda from_pl_id, new_pl_pref: maximizeList( from_pl_id, new_pl_pref ),
        "desc" : [ 
            "Get playlist with the full albums for each track in a list",
            "Params: ( from_pl_id, new_pl_pref )" ]
        },
        
    "maxrrad" : { 
        
        "func" : lambda: maximizeList( "37i9dQZEVXbuX4MySjIacD", "rrad" ),
        "desc" : [
            "Use maxList on Release Radar. Playlist will be prefixed 'rrad'.",
            "Params: none" ]
        
     },
        
    "maxdsco" : { 
        
        "func" : lambda: maximizeList( "37i9dQZEVXcXssf47BUM1F", "dsco" ),
        "desc" : [
            "Use maxList on Discover Weekly. Playlist will be prefixed 'dsco'.",
            "Params: none" ]
        
     },
     
    "shuffle" : { 
        
        "func" : lambda pl_id: distance_shuffle_playlist(pl_id),
        "desc" : [
            "Into new list, shuffle from a list ensuring songs from the same ",
            "album are spaced as widely apart as possible.",
            "Params: (playlist_id)" ]
     },
     
    "libdata" : { 
        
        "func" : lambda asPandas, store: get_library( asPandas, store ),
        "desc" : ( [
            "Get library as dict or pandas dataframe. If store false, return.",
            "Params: ( asPandas (dflt false), store (dflt false) ) " ]
            )
        
     },
     
     "getpcst" : {
        
        "func" : lambda: getLatestEpsFromPodTList(),
        "desc" : [
            "Get latest three episodes from shows collected from a list of ",
            "podcast episodes. Currently three from '2PFeIO0B0DtenFmGKbzYvg'"]
     },     
     
    "help" : { 
        
        "func" : lambda: output_help(),
        "desc" : [ "View command guide" ]
        },
}

def start():
    user_id, sp_cid, sp_sec = fetch_credentials()
    ops = Ops()
    spot = auth_SpotPy( user_id, sp_cid, sp_sec )
    return user_id, sp_cid, sp_sec, ops, spot


def getValidatedInput( args = None ): 
    prompt = "\n\nNew command, 'b' to exit. Arg separator is space\n"
    if not args: args = [ input( prompt ) ]
    # split if separator in single arg, lower first
    if len(args) == 1 and ' ' in args[0]:
        args = args[0].split( " " )
        args = [ args[0].lower() ] + [ arg for arg in args[1:] ]
    # else lower single arg
    elif len(args) == 1:  args[0] = args[0].lower() 
    # if multiple, lower first
    elif len(args) > 1:
        args = ( [ args[0].lower() ] + [ arg for arg in args[ 1: ] ] )
    else: pass # allow empty to fall through to main loop condition
    
    return args

def mainLoop( args ):
    while len(args) > 0:
        if args[0] in cmdLib.keys(): cmdLib[ args[0].lower() ][ "func" ]( *args[1:] )
        elif "".join(args).lower() == "b": break
        else: print( f"\n[ {args[0]} ] is not known command." )
        args = getValidatedInput()

def connect_authenticate_loop():
    while True:
        # try: user_id, sp_cid, sp_sec, ops, spot = start()
        try: return start()
        except Exception as e: 
            print( f"Error during connect-authentic: {type(e).__name__}" )
            print( f"Retrying in three seconds..." )
            time.sleep(3)
        else: break


def startFromArgs( args ):
    args = getValidatedInput( args )
    mainLoop( args )

if __name__ == "__main__":
    user_id, sp_cid, sp_sec, ops, spot = connect_authenticate_loop()
    output_help()
    startFromArgs( sys.argv[1:] ) # omits inital filename arg