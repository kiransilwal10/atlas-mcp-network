import sqlite3
import os

from fastmcp import FastMCP

# Initialize the standalone Flight Server
mcp = FastMCP("Flight-PlaServer")

#defining the local databse file path
DB_FILE = os.path.join(os.path.dirname(__file__), "travel_network.db")

def init_db():
    """Initializes the local SQL database and creates the flights table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_number TEXT NOT NULL,
                departure TEXT NOT NULL,
                arrival TEXT NOT NULL,
                date TEXT NOT NULL
            )
        """)
        conn.commit()
init_db()

@mcp.tool()
def log_flight(flight_number: str, departure: str, arrival: str, date: str) -> str:
    """
    Logs a real flight itinerary into the local relational SQL database.
    Use this tool whenever you need to save, track, or record a new flight layout.
    """

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Insert the flight details cleanly into our structured table
            cursor.execute("""
                INSERT INTO flights (flight_number, departure, arrival, date)
                VALUES (?, ?, ?, ?)
            """, (flight_number.upper(), departure.upper(), arrival.upper(), date))
            conn.commit()
            
        return f"Success: Flight {flight_number.upper()} from {departure.upper()} to {arrival.upper()} on {date} has been permanently logged in SQL database."

    except Exception as e:
        return f"Database Error: Failed to log flight details due to: {str(e)}"
    
if __name__ == "__main__":
    mcp.run()