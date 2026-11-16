"""Vercel entry for the API service. Local development still uses `marswalk serve`."""
from marswalk.api.app import create_app

app = create_app()
