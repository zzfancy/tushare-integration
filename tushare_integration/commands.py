import typer

from tushare_integration.manager import CrawlManager

try:
    from rich import print
except ImportError:
    pass

crawl_app = typer.Typer(name='CrawlManager', help='CrawlManager help', no_args_is_help=True)

query_app = typer.Typer(
    name='QueryManager',
    help='QueryManager help',
    no_args_is_help=True,
)


@query_app.command('list', help="List spiders")
def list_spiders():
    manager = CrawlManager()
    print(manager.list_spiders())


@crawl_app.command('clear', help="Clear table data of spiders", no_args_is_help=True)
def clear_tables(
    spider: str = typer.Argument(..., help="Wildcard of the spiders whose tables will be cleared"),
    yes: bool = typer.Option(False, '--yes', '-y', help="Skip confirmation"),
):
    manager = CrawlManager()
    tables = manager.get_tables(spider)
    if not tables:
        print(f"No spider matches {spider}")
        raise typer.Exit(code=1)

    print(tables)
    if not yes:
        typer.confirm(
            f"Clear all data in {len(tables)} table(s) of database {manager.settings.database.db_name}?", abort=True
        )
    manager.truncate_tables(tables)


@crawl_app.command('job', help="Run a job", no_args_is_help=True)
def run_job(job_name: str = typer.Argument(..., help="Name of the job to run")):
    manager = CrawlManager()
    manager.run_job(job_name)


@crawl_app.command('spider', help="Run spiders", no_args_is_help=True)
def run_spider(
    spider: str = typer.Argument(
        ...,
        help="Wildcard of the spider to run",
    )
):
    manager = CrawlManager()
    manager.run_spider(spider)
