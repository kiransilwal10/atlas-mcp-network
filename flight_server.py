from fastmcp import FastMCP

# Initialize the standalone Flight Server
mcp = FastMCP("Flight-Server")

@mcp.tool()
def book_flight(destination: str, flight_number: str, departure_date: str) -> str:
    """
    Logs and schedules a flight itinerary for a trip.
    Use this tool whenever the user provides travel details, flight numbers, or asks to book a trip.
    """
    # For now, we simulate logging the flight details to your workspace
    print(f"\n--- [FLIGHT BOOKING SIMULATION] ---")
    print(f"Destination: {destination}")
    print(f"Flight Number: {flight_number}")
    print(f"Departure Date: {departure_date}")
    print(f"------------------------------------\n")
    
    return f"Success: Flight {flight_number} to {destination} on {departure_date} has been logged in the travel system."

if __name__ == "__main__":
    mcp.run()