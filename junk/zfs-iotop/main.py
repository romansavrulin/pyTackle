from dash import Dash, dcc, html

import pandas as pd
import datetime as dt
from sqlalchemy import create_engine
import plotly.express as px

start = dt.datetime(2020, 1, 1, 18)

# Initializes database in current directory
disk_engine = create_engine('sqlite:///dat.db')


def timeshift(val, created_at):
    return dt.timedelta(seconds=val) + created_at


def convert(chunk_size=10000, created_at=dt.datetime.now()):
    chunk_num = 0
    index_start = 1

    launch_time = dt.datetime.now()

    for df in pd.read_csv('out.dat', chunksize=chunk_size, iterator=True):

        df['CreatedDate'] = pd.to_datetime(df['record_number'].apply(timeshift, created_at=created_at))

        melted = df.melt(id_vars=["record_number", "CreatedDate", "pool_device"], var_name="operation", value_name="value")
        melted.sort_values("record_number")
        melted.index += index_start

        chunk_num += 1
        print('{} seconds: completed {} rows'.format((dt.datetime.now() - launch_time).seconds, chunk_num * chunk_size))
        melted.to_sql('data', disk_engine, if_exists='append')
        index_start = melted.index[-1] + 1
    exit(0)

# convert()

#hours = 24
#minutes = hours*60
seconds = 60 #minutes*60


avg_df = pd.read_sql_query(
'SELECT '
    'datetime((''strftime(\'%s\', CreatedDate) / {seconds}) * {seconds}, \'unixepoch\') interval, '
    'AVG(value) as value, '
    'pool_device ,'
    'operation '
'FROM data '
    'WHERE pool_device in ("pvdata", "rpool") AND operation <> "operations_read" AND operation <> "operations_write" '
    'GROUP BY pool_device, operation, interval '
    'ORDER BY interval'.format(seconds=seconds), disk_engine)

# iops should be summed??
iops_df = pd.read_sql_query(
'SELECT '
    'datetime((''strftime(\'%s\', CreatedDate) / {seconds}) * {seconds}, \'unixepoch\') interval, '
    'AVG(value) as value, '
    'pool_device ,'
    'operation '
'FROM data '
    'WHERE pool_device in ("pvdata", "rpool") AND (operation = "operations_read" OR operation = "operations_write") '
    'GROUP BY pool_device, operation, interval '
    'ORDER BY interval'.format(seconds=seconds), disk_engine)

df = pd.concat([iops_df, avg_df], ignore_index=True)
devices = df["pool_device"].unique()

fig = px.line(df, x="interval", y="value", color="operation",
            facet_row="pool_device",
            category_orders={"pool_device": ["rpool", "pvdata"]}, title='ZFS stat', log_y=True)
fig.show()

app = Dash()
app.layout = html.Div([
    dcc.Graph(figure=fig)
])

app.run_server(debug=True, use_reloader=True)  # Turn off reloader if inside Jupyter