import pandas as pd

from scrape.pbp import json_pbp, html_pbp, espn_pbp
from scrape.shifts import json_shifts, html_shifts
from scrape import playing_roster, season_schedule, shared

# Holds list for broken games for shifts and pbp
broken_shifts_games = []
broken_pbp_games = []
players_missing_ids = []
espn_games = []

columns = ['Game_Id', 'Date', 'Period', 'Event', 'Description', 'Time_Elapsed', 'Seconds_Elapsed', 'Strength',
           'Ev_Zone', 'Type', 'Ev_Team', 'Home_Zone', 'Away_Team', 'Home_Team', 'p1_name', 'p1_ID', 'p2_name', 'p2_ID',
           'p3_name', 'p3_ID', 'awayPlayer1', 'awayPlayer1_id', 'awayPlayer2', 'awayPlayer2_id', 'awayPlayer3',
           'awayPlayer3_id', 'awayPlayer4', 'awayPlayer4_id', 'awayPlayer5', 'awayPlayer5_id', 'awayPlayer6',
           'awayPlayer6_id', 'homePlayer1', 'homePlayer1_id', 'homePlayer2', 'homePlayer2_id', 'homePlayer3',
           'homePlayer3_id', 'homePlayer4', 'homePlayer4_id', 'homePlayer5', 'homePlayer5_id', 'homePlayer6',
           'homePlayer6_id',  'Away_Players', 'Home_Players', 'Away_Score', 'Home_Score', 'Away_Goalie',
           'Away_Goalie_Id', 'Home_Goalie', 'Home_Goalie_Id', 'xC', 'yC', 'Home_Coach', 'Away_Coach']


def check_goalie(row):
    """
    Checks for bad goalie names (you can tell by them having no player id)
    :param row: df row
    """
    if row['Away_Goalie'] != '' and row['Away_Goalie_Id'] == 'NA':
        players_missing_ids.extend([row['Away_Goalie'], row['Game_Id']])

    if row['Home_Goalie'] != '' and row['Home_Goalie_Id'] == 'NA':
        players_missing_ids.extend([row['Home_Goalie'], row['Game_Id']])


def get_players_json(json):
    """
    Return dict of players for that game
    :param json: gameData section of json
    :return: dict of players->keys are the name (in uppercase)
    """
    players = dict()

    players_json = json['players']
    for key in players_json.keys():
        name = shared.fix_name(players_json[key]['fullName'].upper())
        players[name] = {'id': ' '}
        try:
            players[name]['id'] = players_json[key]['id']
        except KeyError:
            print(name, ' is missing an ID number')
            players[name]['id'] = 'NA'

    return players


def combine_players_lists(json_players, roster_players, game_id):
    """
    Combine the json list of players (which contains id's) with the list in the roster html
    :param json_players: dict of all players with id's
    :param roster_players: dict with home and and away keys for players
    :param game_id:
    :return: dict containing home and away keys -> which contains list of info on each player
    """
    home_players = dict()
    for player in roster_players['Home']:
        try:
            name = shared.fix_name(player[2])
            id = json_players[name]['id']
            home_players[name] = {'id': id, 'number': player[0]}
        except KeyError:
            # This usually means it's the backup goalie (who didn't play) so it's no big deal with them
            if player[1] != 'G':
                players_missing_ids.extend([player, game_id])
                home_players[name] = {'id': 'NA', 'number': player[0]}

    away_players = dict()
    for player in roster_players['Away']:
        try:
            name = shared.fix_name(player[2])
            id = json_players[name]['id']
            away_players[name] = {'id': id, 'number': player[0]}
        except KeyError:
            if player[1] != 'G':
                players_missing_ids.extend([player, game_id])
                away_players[name] = {'id': 'NA', 'number': player[0]}

    return {'Home': home_players, 'Away': away_players}


def combine_html_json_pbp(json_df, html_df, game_id, date):
    """
    Join both data sources
    :param json_df: json pbp DataFrame
    :param html_df: html pbp DataFrame
    :param game_id:
    :param date:
    :return: finished pbp

    Add game_id and date
    Get rid of period, event, time_elapsed
    """
    html_df.Period = html_df.Period.astype(int)
    game_df = pd.merge(html_df, json_df, left_on=['Period', 'Event', 'Seconds_Elapsed'],
                       right_on=['period', 'event', 'seconds_elapsed'], how='left')

    # This id because merge doesn't work well with shootouts
    game_df = game_df.drop_duplicates(subset=['Period', 'Event', 'Description', 'Seconds_Elapsed'])

    try:
        game_df['Game_Id'] = game_id[-5:]
        game_df['Date'] = date
        return pd.DataFrame(game_df, columns=columns)
    except Exception as e:
        print('Problem combining Html Json pbp for game {}'.format(game_id, e))


def combine_espn_html_pbp(html_df, espn_df, game_id, date, away_team, home_team):
    """
    Merge the coordinate from the espn feed into the html DataFrame
    :param html_df: dataframe with info from html pbp
    :param espn_df: dataframe with info from espn pbp
    :param game_id: json game id
    :param date: ex: 2016-10-24
    :param away_team:
    :param home_team
    :return: merged DataFrame
    """
    espn_df.period = espn_df.period.astype(int)
    try:
        df = pd.merge(html_df, espn_df, left_on=['Period', 'Seconds_Elapsed', 'Event'],
                      right_on=['period', 'time_elapsed', 'event'], how='left')

        # df = df.drop_duplicates(subset=['Period', 'Event', 'Seconds_Elapsed'])
        df = df.drop(['period', 'time_elapsed', 'event'], axis=1)
    except Exception as e:
        print('Error for combining espn and html pbp for game {}'.format(game_id), e)
        return None

    df['Game_Id'] = game_id[-5:]
    df['Date'] = date
    df['Away_Team'] = away_team
    df['Home_Team'] = home_team

    return pd.DataFrame(df, columns=columns)


def scrape_pbp(game_id, date, roster):
    """
    Scrapes the pbp
    Automatically scrapes the json and html, if the json is empty the html picks up some of the slack and the espn
    xml is also scraped for coordinates
    :param game_id: json game id
    :param date:
    :param roster: list of players in pre game roster
    :return: DataFrame with info or None if it fails
             a dict of players with id's and numbers
    """
    game_json = json_pbp.get_pbp(game_id)
    try:
        teams = json_pbp.get_teams(game_json)                                    # Get teams from json
        player_ids = get_players_json(game_json['gameData'])
        players = combine_players_lists(player_ids, roster['players'], game_id)  # Combine roster names with player id's
    except Exception as e:
        print('Problem with getting the teams or players', e)
        return None, None

    year = str(game_id)[:4]
    # Coordinates are only available in json from 2010 onwards
    if int(year) >= 2010:
        try:
            json_df = json_pbp.parse_json(game_json)
            num_json_plays = len(game_json['liveData']['plays']['allPlays'])
        except Exception as e:
            print('Error for Json pbp for game {}'.format(game_id), e)
            return None, None
    else:
        num_json_plays = 0

    # Check if the json is missing the plays...if it is enable the HTML parsing to do more work to make up for the
    # json and scrape ESPN for the coordinates
    if num_json_plays == 0:
        espn_games.extend([game_id])
        html_df = html_pbp.scrape_game(game_id, players, teams, False)
        espn_df = espn_pbp.scrape_game(date, teams['Home'], teams['Away'])
        game_df = combine_espn_html_pbp(html_df, espn_df, str(game_id), date, teams['Away'], teams['Home'])
    else:
        html_df = html_pbp.scrape_game(game_id, players, teams, True)
        game_df = combine_html_json_pbp(json_df, html_df, str(game_id), date)

    if game_df is not None:
        game_df['Home_Coach'] = roster['head_coaches']['Home']
        game_df['Away_Coach'] = roster['head_coaches']['Away']

    return game_df, players


def scrape_shifts(game_id, players):
    """
    Scrape the Shift charts (or TOI tables)
    :param game_id: json game id
    :param players: dict of players with numbers and id's
    :param
    :return: DataFrame with info or None if it fails
    """
    year = str(game_id)[:4]
    try:
        if int(year) < 2010:   # Control for fact that shift json is only available from 2010 onwards
            raise Exception
        shifts_df = json_shifts.scrape_game(game_id)
    except Exception:
        try:
            shifts_df = html_shifts.scrape_game(game_id, players)
        except Exception as e:
            broken_shifts_games.extend([game_id])
            print('Error for html shifts for game {}'.format(game_id), e)
            return None

    return shifts_df


def scrape_game(game_id, date, if_scrape_shifts):
    """
    This scrapes the info for the game.
    The pbp is automatically scraped, and the whether or not to scrape the shifts is left up to the user
    :param game_id: game to scrap
    :param date: ex: 2016-10-24
    :param if_scrape_shifts: boolean, check if scrape shifts
    :return: DataFrame of pbp info
             (optional) DataFrame with shift info
    """
    shifts_df = None

    try:
        roster = playing_roster.scrape_roster(game_id)
    except Exception:
        broken_pbp_games.extend([game_id, date])
        return None, None     # Everything fails without the roster

    pbp_df, players = scrape_pbp(game_id, date, roster)

    if pbp_df is None:
        broken_pbp_games.extend([game_id, date])

    if if_scrape_shifts and pbp_df is not None:
        shifts_df = scrape_shifts(game_id, players)

    return pbp_df, shifts_df


def scrape_year(year, if_scrape_shifts):
    """
    Calls scrapeSchedule to get the game_id's to scrape and then calls scrapeGame and combines
    all the scraped games into one DataFrame
    :param year: year to scrape
    :param if_scrape_shifts: boolean, check if scrape shifts
    :return: nothing
    """
    schedule = season_schedule.scrape_schedule(year)

    pbp_dfs = []
    shifts_dfs = []

    for game in schedule:
        print(' '.join(['Scraping game', str(game[0]), game[1]]))
        pbp_df, shifts_df = scrape_game(game[0], game[1], if_scrape_shifts)
        if pbp_df is not None:
            pbp_dfs.extend([pbp_df])
        if shifts_df is not None:
            shifts_dfs.extend([shifts_df])

    season_pbp_df = pd.concat(pbp_dfs)
    season_pbp_df = season_pbp_df.reset_index(drop=True)
    season_pbp_df.to_csv('nhl_pbp{}{}.csv'.format(year, int(year)+1), sep=',')
    season_pbp_df.apply(lambda row: check_goalie(row), axis=1)

    if if_scrape_shifts:
        season_shifts_df = pd.concat(shifts_dfs)
        season_shifts_df = season_shifts_df.reset_index(drop=True)
        season_shifts_df.to_csv('nhl_shifts{}{}.csv'.format(year, int(year)+1), sep=',')


def scrape(seasons, if_shifts):
    """
    Scrape the given seasons
    Pbp is automatically scraped, you decide whether or not for shifts
    :param seasons: list of seasons
    :param if_shifts: boolean -> whether or not to scrape shifts
    """

    for season in seasons:
        scrape_year(season, if_shifts)

    print('Broken pbp:')
    for x in broken_pbp_games:
        print(x)

    print('Broken shifts:')
    for x in broken_shifts_games:
        print(x)

    print('Missing ids')
    global players_missing_ids
    players_missing_ids = list(set(players_missing_ids))  # Get rid of duplicates
    for x in players_missing_ids:
        print(x)

    print('ESPN games')
    for x in espn_games:
        print(x)
