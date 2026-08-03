import logging
import os
import sys
import uvicorn

# Ensure the root directory is in sys.path so 'src' can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configure le logger racine pour que les modules applicatifs (notifications, etc.)
# s'affichent dans la console Uvicorn au niveau INFO.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s: %(message)s",
)

if __name__ == "__main__":
    print("🚀 Starting Ticket Agent Backend...")
    print("📍 API Docs: http://localhost:8000/docs")
    print("📍 Health Check: http://localhost:8000/health")
    
    uvicorn.run(
        "src.api:app", host="0.0.0.0", port=8000, reload=True,
        reload_dirs=["src"],  # only backend source triggers a restart, not data/tests/scripts writes
        timeout_graceful_shutdown=5,  # SSE connections (agent/notifications/stream) poll for
        # disconnection every ~15s; without a bound, uvicorn's default (wait forever) makes
        # Ctrl+C hang until that poll notices the client is gone.
    )
