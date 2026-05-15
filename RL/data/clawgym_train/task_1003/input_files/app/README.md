# Yale Service Tracker

This student-built app helps schedule sign-ups with community partners.

Development setup
- Python: 3.9
- Required environment variable: SECRET_API_KEY (used at build time for API access)
- Local run: docker build -t yserv:latest --build-arg SECRET_API_KEY=$SECRET_API_KEY . && docker run -p 8000:8000 yserv:latest

CI notes (outdated): The CI uses Python 3.11 and passes SECRET_API_KEY into the Docker build.
