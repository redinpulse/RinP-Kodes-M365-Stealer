"""
Main entry point for the Kodes application.
"""
import argparse
import logging
import sys
from .client.main import main as client_main
from .server.app import run_server

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("kodes.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """
    Parse command line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Kodes - Microsoft device authentication and proxy tunneling')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    client_parser = subparsers.add_parser('client', help='Run the client application')
    client_parser.add_argument(
        '-api', '--api-url',
        default=None,
        help='URL of the Kodes API server (default: config api_url)'
    )
    client_parser.add_argument(
        '-c', '--config',
        help='Path to configuration file'
    )
    client_parser.add_argument(
        '--headless',
        action='store_true',
        help='Run in headless mode without UI'
    )
    client_parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not open web browser automatically'
    )
    client_parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    server_parser = subparsers.add_parser('server', help='Run the server application')
    server_parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host address to bind to'
    )
    server_parser.add_argument(
        '-p', '--port',
        type=int,
        default=9000,
        help='Port to listen on'
    )
    server_parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    
    args = parser.parse_args()
    
    if hasattr(args, 'debug') and args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    return args


def main():
    """
    Main function to run the application.
    """
    try:
        args = parse_arguments()

        if args.command == 'client':
            sys.argv.remove('client')
            client_main()
        elif args.command == 'server':
            run_server(host=args.host, port=args.port, debug=args.debug)
        else:
            print("Please specify a command (client or server)")
            print("Run 'python -m kodes --help' for more information")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()