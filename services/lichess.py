import aiohttp

BASE_URL = "https://explorer.lichess.ovh/masters"

async def get_lichess_data(fen: str):
    """
    Query Lichess Masters DB for stats on a given FEN.
    Returns move stats, win rates, top continuations.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(BASE_URL, params={"fen": fen}) as resp:
            if resp.status != 200:
                return {}
            return await resp.json()
