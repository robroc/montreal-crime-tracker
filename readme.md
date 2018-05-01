## Tracking crimes in Montreal

This is the code and the files used to create the Montreal crime tracking app by CBC/Radio-Canada.

* [English version](https://newsinteractives.cbc.ca/montreal-crime/)
* Version en français à venir

[Read a full methodology here](http://cbc.ca/1.4574508).

The app does the following:

1. Fetches crime data from the City of Montreal's [open data portal](http://donnees.ville.montreal.qc.ca/dataset/actes-criminels) (updated every three months).
2. Aggregates crimes into a hexagonal grid of the Island of Montreal and uploads the resulting GeoJSON to Mapbox.
3. Calculates montly numbers and time-of-day frequency for each type of crime and exports them as JSON files to be used with Chart.js
4. Calculates significant changes in the last three months to the same period one year before to signal large increases or decreases in crime (this will be added to the page in a future update).
5. Exports additional supporting data (averages, min/max, etc.) in a JSON file used by the app.

The source data files are in the `src` folder. The resulting data is in `static`

The app is written in Python 3.6 and uses the pandas and geopandas libraries for most of the analysis.

### Usage

This app assumes the following:

* You have a Mapbox account and an API key, which is stored in a dict in a file called `secrets.py`
* You have created a tileset and have its ID stored in `secrets.py`

First, create a virtual environment to keep everything tidy. I use Anaconda.

`conda create -n crimeapp`

Enter the environment:

`source activate crimeapp`

Install the dependencies. Geopandas is a tricky one to install depending on your system. I suggest installing it separately with conda.

`conda install -c conda-forge geopandas`

`conda install --yes --file requirements.txt`

If the second installation commaand fails, try with pip:

`pip install -r requirements.txt`

Then run the app:

`python app.py`
