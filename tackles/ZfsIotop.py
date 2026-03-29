import datetime as dt

import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html
from sqlalchemy import create_engine

from tackles.TackleFactory import TackleFactory


class ZfsIotop(TackleFactory):

    @classmethod
    def arg_parser(cls, subparser):
        subparser.add_argument(
            '--db', type=str, default='dat.db',
            help='Path to SQLite database file (default: dat.db)')
        subparser.add_argument(
            '--seconds', type=int, default=60,
            help='Aggregation bucket size in seconds (default: 60)')
        subparser.add_argument(
            '--pools', type=str, nargs='+', default=['pvdata', 'rpool'],
            help='ZFS pool devices to include (default: pvdata rpool)')
        subparser.add_argument(
            '--port', type=int, default=8050,
            help='Port for the Dash server (default: 8050)')
        subparser.add_argument(
            '--convert', action='store_true',
            help='Import CSV data into the database before visualising')
        subparser.add_argument(
            '--csv', type=str, default='out.dat',
            help='Path to CSV file used with --convert (default: out.dat)')

    def __init__(self, parser):
        super().__init__(parser)
        options, _ = parser.parse_known_args()

        self.db_url = f'sqlite:///{options.db}'
        self.seconds = options.seconds
        self.pools = options.pools
        self.port = options.port
        self.do_convert = options.convert
        self.csv_path = options.csv

    def _convert(self, engine):
        chunk_size = 10000
        index_start = 1
        created_at = dt.datetime.now()
        launch_time = dt.datetime.now()

        for chunk_num, df in enumerate(
            pd.read_csv(self.csv_path, chunksize=chunk_size, iterator=True), start=1
        ):
            df['CreatedDate'] = pd.to_datetime(
                df['record_number'].apply(
                    lambda val: dt.timedelta(seconds=val) + created_at
                )
            )
            melted = df.melt(
                id_vars=['record_number', 'CreatedDate', 'pool_device'],
                var_name='operation',
                value_name='value',
            )
            melted.sort_values('record_number', inplace=True)
            melted.index += index_start
            melted.to_sql('data', engine, if_exists='append')
            index_start = melted.index[-1] + 1
            elapsed = (dt.datetime.now() - launch_time).seconds
            print(f'{elapsed}s: imported {chunk_num * chunk_size} rows')

    def _build_figure(self, engine):
        pools_sql = ', '.join(f'"{p}"' for p in self.pools)
        s = self.seconds

        bucket = (
            f"datetime((strftime('%s', CreatedDate) / {s}) * {s}, 'unixepoch') interval"
        )

        avg_df = pd.read_sql_query(
            f"SELECT {bucket}, AVG(value) as value, pool_device, operation "
            f"FROM data "
            f"WHERE pool_device in ({pools_sql}) "
            f"  AND operation NOT IN ('operations_read', 'operations_write') "
            f"GROUP BY pool_device, operation, interval "
            f"ORDER BY interval",
            engine,
        )

        iops_df = pd.read_sql_query(
            f"SELECT {bucket}, AVG(value) as value, pool_device, operation "
            f"FROM data "
            f"WHERE pool_device in ({pools_sql}) "
            f"  AND operation IN ('operations_read', 'operations_write') "
            f"GROUP BY pool_device, operation, interval "
            f"ORDER BY interval",
            engine,
        )

        df = pd.concat([iops_df, avg_df], ignore_index=True)
        return px.line(
            df,
            x='interval',
            y='value',
            color='operation',
            facet_row='pool_device',
            category_orders={'pool_device': self.pools},
            title='ZFS I/O stat',
            log_y=True,
        )

    def do(self):
        engine = create_engine(self.db_url)

        if self.do_convert:
            self._convert(engine)

        fig = self._build_figure(engine)

        app = Dash()
        app.layout = html.Div([dcc.Graph(figure=fig)])
        app.run_server(debug=True, use_reloader=False, port=self.port)
