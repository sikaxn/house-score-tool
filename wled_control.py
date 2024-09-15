import requests

# WLED device IP address
wled_ip = "10.0.0.162"
segments_info = []

def wled_init():
    """
    Initialize the WLED by loading preset 1 and reading segment information.
    This function should always be called first.
    """
    global segments_info

    try:
        # Load preset 1 using the correct JSON API call
        response = requests.post(f"http://{wled_ip}/json/state", json={"ps": 1})
        response.raise_for_status()

        # Get the current state to read segments information
        response = requests.get(f"http://{wled_ip}/json/state")
        response.raise_for_status()

        # Parse the JSON response to get segment information
        data = response.json()
        segments_info = data.get('seg', [])

        # Output the number of segments and their LED counts
        print(f"Preset 1 loaded. Number of segments: {len(segments_info)}")
        for i, segment in enumerate(segments_info):
            print(f"Segment {i+1}: {segment['start']} to {segment['stop']} LEDs ({segment['len']} LEDs)")

    except requests.RequestException as e:
        print(f"Error initializing WLED device: {e}")


def wled_setpercentage(segment, percentage):
    """
    Turn on a percentage of lights on a specific segment using the colors from preset 1.
    """
    if segment == 0:
        print("Segment 0 is not allowed.")
        return

    if not segments_info:
        print("Segments information not loaded. Call wled_init() first.")
        return

    if segment > len(segments_info) or segment < 1:
        print(f"Invalid segment number. Please choose a segment between 1 and {len(segments_info)}.")
        return

    try:
        # Calculate the number of LEDs to turn on based on the percentage
        segment_info = segments_info[segment - 1]
        total_leds = segment_info['len']
        leds_to_turn_on = int((percentage / 100) * total_leds)

        # Generate JSON payload to turn on the specified percentage of LEDs in the segment
        payload = {
            "seg": [
                {
                    "id": segment - 1,  # Segment IDs are zero-based in the API
                    "on": True,
                    "fx": 0,  # Static mode (no effect)
                    "sx": 0,  # Effect speed (irrelevant for static)
                    "ix": 255,  # Full intensity
                    "start": segment_info['start'],
                    "stop": segment_info['stop'],
                    "col": [segment_info.get('col', [[255, 255, 255]])[0]],  # Use the first color from the preset
                    "rng": [{"start": segment_info['start'], "stop": segment_info['start'] + leds_to_turn_on}]
                }
            ]
        }

        # Send the request to update the WLED state
        response = requests.post(f"http://{wled_ip}/json/state", json=payload)
        response.raise_for_status()

        print(f"Set {percentage}% of LEDs on segment {segment}.")

    except requests.RequestException as e:
        print(f"Error setting percentage for segment {segment}: {e}")


def wled_setwhite(segment):
    """
    Set all LEDs in the specified segment to white.
    """
    if not segments_info:
        print("Segments information not loaded. Call wled_init() first.")
        return

    if segment > len(segments_info) or segment < 1:
        print(f"Invalid segment number. Please choose a segment between 1 and {len(segments_info)}.")
        return

    try:
        # Create the payload to set the segment to white
        payload = {
            "seg": [
                {
                    "id": segment - 1,  # Segment IDs are zero-based in the API
                    "on": True,
                    "fx": 0,  # Static mode (no effect)
                    "col": [[255, 255, 255]],  # White color
                    "start": segments_info[segment - 1]['start'],
                    "stop": segments_info[segment - 1]['stop'],
                }
            ]
        }

        # Send the request to update the WLED state
        response = requests.post(f"http://{wled_ip}/json/state", json=payload)
        response.raise_for_status()

        print(f"Segment {segment} set to white.")

    except requests.RequestException as e:
        print(f"Error setting segment {segment} to white: {e}")

# Example Usage
wled_init()
#wled_setpercentage(2, 6)  # Set 10% of LEDs in segment 1 to turn on
wled_setwhite(1)  # Set segment 1 to white
