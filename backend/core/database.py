from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
def create_engine_for(path: str | Path):
    url = str(path) if str(path).startswith('sqlite:') or str(path)==':memory:' else f'sqlite:///{path}'
    engine=create_engine(url,connect_args={'check_same_thread':False,'timeout':5},future=True)
    @event.listens_for(engine,'connect')
    def _pragmas(conn, _):
        c=conn.cursor(); c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=5000'); c.close()
    return engine
def session_factory(engine): return sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
@contextmanager
def session_scope(factory):
    s=factory()
    try: yield s; s.commit()
    except Exception: s.rollback(); raise
    finally: s.close()
