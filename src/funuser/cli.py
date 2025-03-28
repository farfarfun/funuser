import click
import uvicorn
import os
import signal
import sys
from pathlib import Path

PID_FILE = Path.home() / ".funuser" / "funuser.pid"

def ensure_pid_dir():
    pid_dir = PID_FILE.parent
    pid_dir.mkdir(parents=True, exist_ok=True)

def write_pid(pid):
    ensure_pid_dir()
    PID_FILE.write_text(str(pid))

def read_pid():
    try:
        return int(PID_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None

def remove_pid():
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass

@click.group()
def cli():
    """User Management System CLI"""
    pass

@cli.command()
@click.option('--host', default='127.0.0.1', help='Host to bind.')
@click.option('--port', default=8000, help='Port to bind.')
@click.option('--reload', is_flag=True, help='Enable auto-reload.')
def start(host, port, reload):
    """Start the User Management System server"""
    # Check if server is already running
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, 0)  # Check if process exists
            click.echo(f"Server is already running with PID {pid}")
            return
        except OSError:
            remove_pid()
    
    if not reload:  # Only write PID in non-reload mode
        write_pid(os.getpid())
    
    click.echo(f"Starting server at http://{host}:{port}")
    uvicorn.run(
        "funuser.main:app",
        host=host,
        port=port,
        reload=reload
    )

@cli.command()
def stop():
    """Stop the User Management System server"""
    pid = read_pid()
    if not pid:
        click.echo("No server is running")
        return
    
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Server (PID {pid}) has been stopped")
        remove_pid()
    except ProcessLookupError:
        click.echo("Server is not running")
        remove_pid()
    except PermissionError:
        click.echo("Permission denied to stop the server")

@cli.command()
def status():
    """Check the server status"""
    pid = read_pid()
    if not pid:
        click.echo("Server is not running")
        return
    
    try:
        os.kill(pid, 0)
        click.echo(f"Server is running with PID {pid}")
    except OSError:
        click.echo("Server is not running")
        remove_pid()

if __name__ == '__main__':
    cli()
