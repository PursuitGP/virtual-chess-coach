from fastapi import FastAPI
from routes import games

app = FastAPI(title="Virtual Chess Coach Backend")

# Include routes
app.include_router(games.router)
