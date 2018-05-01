import requests
import pandas as pd
import numpy as np
import geopandas 
import geopandas.tools
from shapely.geometry import Point
from secrets import secrets
from mapbox import Uploader
import json, time

CSV_PATH = 'src/interventionscitoyendo.csv'

# Fetch data from open data portal
def get_latest_data():
    data_url = 'http://donnees.ville.montreal.qc.ca/dataset/5829b5b0-ea6f-476f-be94-bc2b8797769a/resource/c6f482bf-bf0f-4960-8b2f-9982c211addd/download/interventionscitoyendo.csv'
    r = requests.get(data_url)
    with open(CSV_PATH, 'wb') as f:
        f.write(r.content)

# Create pandas dataframe from CSV
def make_df():
    print('Fetching latest data...')
    df = pd.read_csv(CSV_PATH, encoding='latin-1', parse_dates = ['DATE'])
    df.DATE = pd.to_datetime(df.DATE, format='%Y-%m-%d')
    return df

def get_crime_categories():
    categories = df.CATEGORIE.unique().tolist()
    if len(categories) > 6:
        print('\n!!!!!!!!! \n ALERT: New crime category added \n!!!!!!!!! \n')
    return categories 

def get_most_recent_date():
    return df.tail(1)['DATE']
    
def localized_date_string(date, lang):
    import locale
    locale.setlocale(locale.LC_TIME, '{}-CA'.format(lang))
    if lang == 'fr':
        return date.dt.strftime('%d %B %Y').iloc[0]
    else:
        return date.dt.strftime('%B %d, %Y').iloc[0]
    
def calculate_daily_average():
    num_days = len(df.DATE.unique())
    total_by_cat =  df.groupby('CATEGORIE').size()
    return (total_by_cat / num_days).round(1).to_dict()

def calculate_time_average(period):
    ''' Use period = 'M' for month, 'W' for week'''
    
    if period not in ['M', 'W']:
        print("Only valid arguments for time sampling are 'M' or 'W'")
        raise
    periods = df.set_index('DATE').resample(period).count()
    num_periods = len(periods.index.unique())
    total_by_cat =  df.groupby('CATEGORIE').size()
    return (total_by_cat / num_periods).round(1).to_dict()

# Creates a dataframe of the last x months in the data, and the same period the year before
# to compare changes YOY
def get_last_x_months(months):
    by_date = df.set_index('DATE').sort_index()
    by_date['geometry'] = by_date.apply(lambda row: Point(row['LONG'], row['LAT']), axis=1)
    by_date = geopandas.GeoDataFrame(by_date, geometry='geometry')
    by_date = by_date[(by_date.LAT > 45) & (by_date.LONG < -70)]
    by_date.crs = {'init': 'epsg:4326'}
    last_date = by_date.index[-1]
    start_date = last_date - pd.tseries.offsets.MonthBegin(months)
    last_x_months = by_date[start_date:]
    start_date_last_year = start_date - pd.DateOffset(years=1)
    last_date_last_year = start_date_last_year + pd.DateOffset(months=months)
    x_months_last_year = by_date[start_date_last_year: last_date_last_year]
    return last_x_months.reset_index(), x_months_last_year.reset_index()

    

# Create a JSON for dates and crime counts for each crime type for Charts.js
# This one aggregates by month for all data to create line charts
column_order = ['Vol de véhicule à moteur',
'Vol dans / sur véhicule à moteur',
'Introduction',
'Méfait',
'Vols qualifiés',
'Infractions entrainant la mort']

def prepare_linechart_json(lang, time_sample='month'):
    from pandas.tseries.offsets import MonthEnd
    
    print('Preparing line charts...')
    crimes_json = {}
    graphs_array = []
    
    # Ensure the data ends at the latest full month
    latest_date = get_most_recent_date()
    if latest_date.dt.is_month_end.bool() == False:
        latest_date = latest_date - MonthEnd(1)
    
    month_averages = calculate_time_average('M')
    week_averages = calculate_time_average('W')
    if time_sample == 'week':
        by_time = ( df.groupby('CATEGORIE')
             .apply(lambda g: g.set_index('DATE')['QUART'].resample('W').count())
             .unstack(level=0)
             .fillna(0)
             )
    else:
        by_time = ( df.set_index('DATE')
             .loc[:latest_date.dt.date.iloc[0]]
             .groupby('CATEGORIE')         
             .resample('M').count()
             .unstack(level=0)['CATEGORIE']
             .fillna(0)
             )
    
    by_time = by_time[column_order]
    date_labels = by_time.index.strftime('%Y-%m-%d').tolist()
    crimes_json['labels'] = date_labels

    for cat in by_time.columns:
        temp_df = by_time[cat]
        data = temp_df.values.astype(int).tolist()
        cat_label = cat
        if lang == 'en':
            cat_label = category_translations[cat]
        graphs_array.append({'title' : cat_label, 
                            'data': data, 
                            'averageWeek' : week_averages[cat],
                            'averageMonth' : month_averages[cat]})
        
    crimes_json['graphs'] = graphs_array
    crimes_json = 'var lineCharts = ' + json.dumps(crimes_json, ensure_ascii=False)
    return crimes_json

# This one is for pie charts by time of day
def prepare_time_json(lang):
    print('Preparing pie charts...')
    time_json = {}
    graphs_array = []
    time_day = ( df.groupby(['CATEGORIE','QUART'])
                    .size()
                    .reset_index()
                    .rename(columns={0: 'count'})
                    .pivot_table('count', index='CATEGORIE', columns='QUART')
                )[['jour', 'soir', 'nuit']]
    time_day = time_day.div(time_day.sum(1), axis=0).round(3) * 100
    time_day = time_day.reindex(column_order)
    time_labels = time_day.columns.tolist()
    if lang == 'en':
        time_labels = ['day', 'evening', 'night']
    time_json['labels'] = time_labels
    for i in time_day.index:
        data = time_day.loc[i].values.tolist()
        cat_label = i
        if lang == 'en':
            cat_label = category_translations[i]
        graphs_array.append({ 'title' : cat_label,
                              'data' : data }) 
    time_json['graphs'] = graphs_array
    time_data_json = 'var pieCharts = ' + json.dumps(time_json, ensure_ascii=False)
    return time_data_json

# Process and export geo data. This counts the number of crimes in a hexgrid and calculates hexes with major changes YOY
def prepare_geo_data(time_range = 'all'):
    print('Preparing hexbinned data...')
    # Load geoDataFrame
    data = df

    data['geometry'] = data.apply(lambda row: Point(row['LONG'], row['LAT']), axis=1)
    geodf = geopandas.GeoDataFrame(data, geometry='geometry')
    geodf = geodf[(geodf.LAT > 45) & (geodf.LONG < -70)]
    geodf.crs = {'init': 'epsg:4326'}
    geodf.DATE = geodf.DATE.dt.strftime('%Y-%m-%d')

     # Prepare hexgrid
    hexes = geopandas.GeoDataFrame.from_file('src/hex_island_pop.shp')
    hexes = hexes[['POP', 'geometry']]
    hexes = hexes.reset_index().rename(columns={'index': 'id'})
    hexes.id = hexes.id.astype(str)
    hexes.crs = {'init': 'epsg:4326'}

     # Calculate crimes per hex
    joined = geopandas.tools.sjoin(geodf, hexes, how='inner', op='within')
    joined = joined[['CATEGORIE', 'DATE', 'QUART', 'PDQ', 'geometry','index_right']]

    per_hex = joined.reset_index().groupby(['index_right', 'CATEGORIE']).size().reset_index().rename(columns={0:'count'})
    per_hex.index_right = per_hex.index_right.astype(int)
    per_hex = per_hex.pivot(index='index_right', columns='CATEGORIE', values='count').reset_index()
    per_hex.rename(columns={'index_right':'id'}, inplace=True)
    per_hex.id = per_hex.id.astype(str)

    # Fill missing hexes with null data
    # First, find which hexes don't have data
    missing = []
    hexixlist = [str(x) for x in hexes.index.tolist()] # 967 items
    for ix in hexixlist:
        if ix not in per_hex.id.tolist():
            missing.append(ix)

    # Create empty dataframe with null values and append to data
    num_rows = len(per_hex.id.unique())
    nullvalues = pd.DataFrame(index=np.arange(num_rows, len(hexes)), columns = per_hex.columns)
    nullvalues.id = missing
    per_hex = per_hex.append(nullvalues)
    # Replace NaNs with 0
    num_cols = per_hex.columns[1:]
    per_hex[num_cols] = per_hex[num_cols].fillna(0).astype(int)

    return hexes, per_hex

# Calculate significant changes between last update and same period a year before.
def calculate_changes():
    first_months, last_months = get_last_x_months(3)

    print('Calculating changes from last 3 months...')
    first_three_hex = geopandas.tools.sjoin(first_months, hexes, how='inner', op='within')
    first_three_hex = first_three_hex[['CATEGORIE', 'DATE', 'QUART', 'PDQ', 'geometry','index_right']]
    per_hex_f3 = (first_three_hex
                    .reset_index()
                    .groupby(['index_right', 'CATEGORIE'])
                    .size()
                    .reset_index()
                    .rename(columns={0:'count'}))
    per_hex_f3.index_right = per_hex_f3.index_right.astype(int)

    last_three_hex = geopandas.tools.sjoin(last_months, hexes, how='inner', op='within')
    last_three_hex = last_three_hex[['CATEGORIE', 'DATE', 'QUART', 'PDQ', 'geometry','index_right']]
    per_hex_l3 = (last_three_hex
                    .reset_index()
                    .groupby(['index_right', 'CATEGORIE'])
                    .size()
                    .reset_index()
                    .rename(columns={0:'count'}))
    per_hex_l3.index_right = per_hex_l3.index_right.astype(int)

    changes = per_hex_f3.merge(per_hex_l3, on=['index_right','CATEGORIE'], suffixes=('_first', '_last'))
    changes['diff'] = (changes['count_last']/changes['count_first'] - 1) *100
    
    # Filter hexes with >20% increases OR <20% decreases and at least 10 incidents in the "before" data
    changes = ( changes[((changes['diff'] >= 20) | (changes['diff'] <= -20)) & (changes['count_first'] >= 10 )]
                .rename(columns={'index_right':'id'})
                .pivot(index='id', columns='CATEGORIE', values='diff').reset_index()
                )
    changes.id = changes.id.astype(str)
    return changes

# Calculate average crime counts for each hex
def calculate_means_per_hex(gdf):
    return gdf.mean(numeric_only=True)[1:].round(1).to_dict()

# Get max/min of crimes for legend
def get_maxmin(df):
    return {'max' : df.set_index('id').max().max(),
            'min' : df[df >= 1].set_index('id').min().min()
            }

# Joins data to hexgrid
def make_geodataframe(shp, data):
    hexes_with_data = shp.reset_index().merge(data, on='id').drop('POP', axis=1).fillna(0)
    return hexes_with_data

# Converts geodataframe to GeoJSON
def make_geojson(gdf):
    # Export geoJson of hexgrid with data
    geojson = json.loads(gdf.set_index('id').to_json())
    return geojson 
    
def lowercase_fields(df):
    df.columns = (df.columns.str.lower()
     .str.replace('/','')
     .str.replace('  ',' ')
     .str.replace(' ','_')
     .str.replace('à','a')
     .str.replace('é','e') )
    return df.columns

def update_mapbox_tileset(dataset, lang): 
    print('Uploading {} version to Mapbox'.format(lang.upper()))
    
    MAPBOX_API_KEY = secrets['MAPBOX_API_KEY']
    TILESET_ID = secrets['TILESET_ID_' + lang.upper()]
    
    def init_upload():
        with open('src/hexes_crime_{}.geojson'.format(lang), 'rb') as src:
            upload_resp = uploader.upload(src, TILESET_ID)
            return upload_resp
     
    # Write geodataframe to JSON file to be read into Mapbox
    with open('src/hexes_crime_{}.geojson'.format(lang), 'w', encoding='utf-8') as out:
        out.write(dataset.to_json())
    
    uploader = Uploader(MAPBOX_API_KEY)
    upload_resp = init_upload()

    # Keep trying if upload doesn't succeed
    if upload_resp.status_code == 422:
        print('Update unsuccessful. Retrying...')
        while True:
            time.sleep(5)
            upload_resp = init_upload()
            if upload_resp.status_code != 422:
                break
    
    # If upload successful, check on status
    if upload_resp.status_code == 201:
        upload_id = upload_resp.json()['id']
        while True:
            status_resp = uploader.status(upload_id).json()
            if status_resp['complete']:
                print('Mapbox tileset update successful.')
                break
            time.sleep(5)
    else:
        raise Exception('Unable to connect to Mapbox.')


# Global variables
get_latest_data()
df = make_df()
category_translations = {
    'Infractions entrainant la mort' : 'Fatal crimes',
    'Introduction' : 'Breaking and entering',
    'Méfait' : 'Mischief',
    'Vol dans / sur véhicule à moteur' : 'Theft from a vehicle',
    'Vol de véhicule à moteur' : 'Car theft',
    'Vols qualifiés' : 'Armed robbery'
    }

# Main function that sends data to Mapbox and packages all JS files
def index():     
    # Start with geo files
    hexgrid, geo_data = prepare_geo_data()
    crime_gdf = make_geodataframe(hexgrid, geo_data)
    
    # These will be activated in a future update:
    #changes = calculate_change()
    #changes_gdf = make_geodataframe(hexgrid, changes)
    
    for lang in ['fr', 'en']:
    
        print('\nPROCESSING DATA IN {} '.format(lang.upper()))
        
        crime_categories = get_crime_categories()
        if lang == 'en':
            crime_gdf = crime_gdf.rename(columns = category_translations)
            crime_categories = [category_translations[crime] for crime in crime_categories]
        mean_per_hex = calculate_means_per_hex(crime_gdf)

        # Write data to Mapbox
        update_mapbox_tileset(crime_gdf, lang)
    
        # Package data for charts    
        linechart_json = prepare_linechart_json(lang)
        times_of_crimes_json = prepare_time_json(lang)
        with open('static/{}/js/crime_charts.js'.format(lang), 'w', encoding='utf-8') as f:
            f.write(linechart_json + ';')
            f.write('\n')
            f.write(times_of_crimes_json + ';')
            
        # Other supporting data can go into a single JSON
        latest_date = get_most_recent_date()
        date_string = localized_date_string(latest_date, lang)
        maxmin = get_maxmin(geo_data)

        object_dict = {
            'crime_categories': crime_categories, 
            'mean_per_hex' : mean_per_hex,
            'max' : int(maxmin['max']),
            'min' : int(maxmin['min']),
            'latest_date' : date_string
            }
        
        with open('static/{}/js/supporting_data.js'.format(lang), 'w', encoding='utf-8') as f:
            f.write('var supportingData = ' + json.dumps(object_dict, ensure_ascii=False))
            print('Exporting supporting data...')
        
        print('\n-----------------------\n')
            

    print('App update complete.')
    
if __name__ == '__main__':
    index()