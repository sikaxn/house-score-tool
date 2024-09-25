import threading
import json
import time
import os
from flask import Flask, render_template_string, request, redirect, url_for
import pygame
import multiprocessing
import portalocker  # For file locking
import math
from sacn import sACNsender
from gtts import gTTS  # For text-to-speech
import tempfile  # For creating temporary files

# Initialize teams and save to a JSON file if not present
initial_teams = [
    {'name': 'Red', 'score': 0, 'color': [255, 0, 0]},
    {'name': 'Blue', 'score': 0, 'color': [0, 0, 255]},
    {'name': 'Yellow', 'score': 0, 'color': [255, 255, 0]},
    {'name': 'Green', 'score': 0, 'color': [0, 255, 0]}
]

# Default sACN IP address for WLED
sacn_ip_address = '10.0.0.162'

# Initialize sound and TTS settings
sound_enabled = True
tts_enabled = True
sound_effect_file_add = 'point_add.wav'       # Make sure this file exists
sound_effect_file_subtract = 'point_taken.wav'  # Make sure this file exists

# Initialize Pygame and mixer
pygame.init()
pygame.mixer.init()

# Save initial teams to JSON file if not present
def initialize_teams():
    try:
        with open('teams.json', 'x') as f:
            json.dump(initial_teams, f)
    except FileExistsError:
        pass  # File already exists

    # Initialize settings.json if not present
    try:
        with open('settings.json', 'x') as f:
            json.dump({'sound_enabled': True, 'tts_enabled': True}, f)
    except FileExistsError:
        pass  # File already exists

# File read/write functions with locking
def read_teams():
    with portalocker.Lock('teams.json', 'r', timeout=5) as f:
        return json.load(f)

def write_teams(teams):
    with portalocker.Lock('teams.json', 'w', timeout=5) as f:
        json.dump(teams, f)

def read_config():
    try:
        with portalocker.Lock('config.json', 'r', timeout=5) as f:
            return json.load(f)
    except FileNotFoundError:
        return {'sacn_ip': sacn_ip_address}  # Default configuration

def write_config(config):
    with portalocker.Lock('config.json', 'w', timeout=5) as f:
        json.dump(config, f)

# Functions to read/write settings
def read_settings():
    try:
        with portalocker.Lock('settings.json', 'r', timeout=5) as f:
            return json.load(f)
    except FileNotFoundError:
        return {'sound_enabled': True, 'tts_enabled': True}

def write_settings(settings):
    with portalocker.Lock('settings.json', 'w', timeout=5) as f:
        json.dump(settings, f)

# Flask App
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    # Read current teams
    try:
        teams = read_teams()
    except Exception as e:
        return f"Error reading teams: {e}", 500

    # Read settings
    settings = read_settings()
    sound_enabled = settings['sound_enabled']
    tts_enabled = settings['tts_enabled']

    if request.method == 'POST':
        if 'adjust' in request.form:
            # Update scores based on button clicked
            try:
                team_index = int(request.form.get('team_index'))
                action = request.form.get('action')

                if action:
                    points = int(action)
                    old_score = teams[team_index]['score']
                    teams[team_index]['score'] += points
                    if teams[team_index]['score'] < 0:
                        teams[team_index]['score'] = 0  # Prevent negative scores

                    # Save updated teams to JSON file
                    write_teams(teams)

                    # Update sACN after score adjustment
                    update_sacn()

                    # Play sound effect if enabled
                    if sound_enabled:
                        play_sound_effect(points)

                    # Announce score change via TTS if enabled
                    if tts_enabled:
                        score_change = teams[team_index]['score'] - old_score
                        announce_score_change(teams[team_index]['name'], score_change)

                    return redirect(url_for('index'))
                else:
                    return "Invalid request.", 400
            except Exception as e:
                return f"Error updating scores: {e}", 500
        elif 'announce_team' in request.form:
            # Announce individual team score
            try:
                team_index = int(request.form.get('team_index'))
                if tts_enabled:
                    announce_team_score(teams[team_index])
                return redirect(url_for('index'))
            except Exception as e:
                return f"Error announcing team score: {e}", 500
        elif 'announce_all' in request.form:
            # Announce all teams' scores
            try:
                if tts_enabled:
                    announce_all_scores(teams)
                return redirect(url_for('index'))
            except Exception as e:
                return f"Error announcing all scores: {e}", 500
        elif 'toggle_sound' in request.form:
            # Toggle sound effect setting
            settings['sound_enabled'] = not sound_enabled
            write_settings(settings)
            return redirect(url_for('index'))
        elif 'toggle_tts' in request.form:
            # Toggle TTS setting
            settings['tts_enabled'] = not tts_enabled
            write_settings(settings)
            return redirect(url_for('index'))
        else:
            return "Invalid request.", 400
    else:
        # Render page with current teams
        return render_template_string('''
            <!doctype html>
            <title>Team Scores</title>
            <h1>Team Scores</h1>

            <h2>Adjust Scores:</h2>
            <table>
                {% for team in teams %}
                <tr>
                    <td><b>{{ team['name'] }}</b> (Score: {{ team['score'] }})</td>
                    <td>
                        <form method="post" style="display:inline;">
                            <input type="hidden" name="team_index" value="{{ loop.index0 }}">
                            <input type="hidden" name="adjust" value="true">
                            <button name="action" value="1">+1</button>
                            <button name="action" value="2">+2</button>
                            <button name="action" value="3">+3</button>
                            <button name="action" value="-1">-1</button>
                            <button name="action" value="-2">-2</button>
                            <button name="action" value="-3">-3</button>
                        </form>
                        <!-- Announce individual team score -->
                        <form method="post" style="display:inline;">
                            <input type="hidden" name="team_index" value="{{ loop.index0 }}">
                            <input type="hidden" name="announce_team" value="true">
                            <button type="submit">Announce Score</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>

            <!-- Announce all scores -->
            <form method="post">
                <input type="hidden" name="announce_all" value="true">
                <button type="submit">Announce All Scores</button>
            </form>

            <!-- Toggle sound and TTS -->
            <form method="post" style="display:inline;">
                <input type="hidden" name="toggle_sound" value="true">
                <button type="submit">{{ 'Disable' if sound_enabled else 'Enable' }} Sound Effects</button>
            </form>
            <form method="post" style="display:inline;">
                <input type="hidden" name="toggle_tts" value="true">
                <button type="submit">{{ 'Disable' if tts_enabled else 'Enable' }} Text-to-Speech</button>
            </form>

            <p><a href="{{ url_for('config') }}">Go to Configuration Page</a></p>
        ''', teams=teams, sound_enabled=sound_enabled, tts_enabled=tts_enabled)

@app.route('/config', methods=['GET', 'POST'])
def config():
    # Read current teams
    try:
        teams = read_teams()
    except Exception as e:
        return f"Error reading teams: {e}", 500

    config = read_config()
    current_sacn_ip = config['sacn_ip']

    if request.method == 'POST':
        if 'set_teams' in request.form:
            # Manually set the scores and names
            try:
                for i in range(len(teams)):
                    name_key = f'name_{i}'
                    score_key = f'score_{i}'
                    teams[i]['name'] = request.form[name_key]
                    teams[i]['score'] = max(0, int(request.form[score_key]))
                # Save updated teams to JSON file
                write_teams(teams)
                return redirect(url_for('config'))
            except Exception as e:
                return f"Error setting teams: {e}", 500
        elif 'reset_scores' in request.form:
            # Reset all team scores to 0
            try:
                for team in teams:
                    team['score'] = 0
                # Save updated teams to JSON file
                write_teams(teams)

                # Update sACN after resetting scores
                update_sacn()

                return redirect(url_for('config'))
            except Exception as e:
                return f"Error resetting scores: {e}", 500
        elif 'set_sacn_ip' in request.form:
            # Set the sACN IP address
            new_ip = request.form.get('sacn_ip')
            config['sacn_ip'] = new_ip
            write_config(config)
            return redirect(url_for('config'))
        else:
            return "Invalid request.", 400
    else:
        # Render configuration page with current teams and sACN IP setting
        return render_template_string('''
            <!doctype html>
            <title>Configuration Page</title>
            <h1>Configuration Page</h1>

            <h2>Set Team Names and Scores Manually:</h2>
            <form method="post">
                <input type="hidden" name="set_teams" value="true">
                {% for team in teams %}
                <b>Team {{ loop.index }}:</b><br>
                Name: <input type="text" name="name_{{ loop.index0 }}" value="{{ team['name'] }}"><br>
                Score: <input type="number" name="score_{{ loop.index0 }}" min="0" value="{{ team['score'] }}"><br><br>
                {% endfor %}
                <input type="submit" value="Update Teams">
            </form>

            <h2>Reset All Scores:</h2>
            <form method="post">
                <input type="hidden" name="reset_scores" value="true">
                <input type="submit" value="Reset Scores">
            </form>

            <h2>Set sACN IP Address:</h2>
            <form method="post">
                <input type="hidden" name="set_sacn_ip" value="true">
                IP Address: <input type="text" name="sacn_ip" value="{{ current_sacn_ip }}"><br><br>
                <input type="submit" value="Update sACN IP">
            </form>

            <p><a href="{{ url_for('index') }}">Back to Main Page</a></p>
        ''', teams=teams, current_sacn_ip=current_sacn_ip)

def run_flask():
    app.run(debug=False)

def create_flask_thread():
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    return flask_thread

def run_main_pygame():
    pygame.init()
    screen = pygame.display.set_mode((800, 600), pygame.RESIZABLE)
    pygame.display.set_caption('Projector')
    screen_width, screen_height = screen.get_size()

    # Font settings
    MAX_FONT_SIZE = 100
    MIN_FONT_SIZE = 10
    score_font = pygame.font.SysFont(None, 24)  # Fixed size for scores

    # Initialize teams
    try:
        teams = read_teams()
    except Exception as e:
        print(f"Error reading teams: {e}")
        return
    prev_teams = [team.copy() for team in teams]

    animation_start_time = None
    animation_duration = 1.0  # Animate over one second

    running = True
    clock = pygame.time.Clock()

    while running:
        dt = clock.tick(60) / 1000.0  # Delta time in seconds

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                # Adjust the screen size
                screen_width, screen_height = event.size
                screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE)

        # Read teams from JSON file
        try:
            current_teams = read_teams()
        except Exception as e:
            print(f"Error reading teams: {e}")
            continue  # Skip this frame

        # Check if teams have changed
        if current_teams != teams:
            prev_teams = [team.copy() for team in teams]
            teams = [team.copy() for team in current_teams]
            animation_start_time = time.time()

            # Update sACN when teams change
            update_sacn()

        # Calculate total scores
        total_prev_score = sum([max(0, team['score']) for team in prev_teams])
        total_current_score = sum([max(0, team['score']) for team in teams])
        if total_prev_score == 0:
            total_prev_score = 1  # Avoid division by zero
        if total_current_score == 0:
            total_current_score = 1  # Avoid division by zero

        # Calculate animation progress
        if animation_start_time is not None:
            elapsed_time = time.time() - animation_start_time
            t = min(elapsed_time / animation_duration, 1.0)
        else:
            t = 1.0  # No animation in progress

        # Draw background
        screen.fill((0, 0, 0))

        x_offset = 0
        small_areas = []

        for i in range(len(teams)):
            team = teams[i]
            team_name = team['name']
            team_color = team['color']

            prev_team = prev_teams[i]
            prev_score = max(0, prev_team['score'])
            current_score = max(0, team['score'])

            # Interpolate scores
            interp_score = prev_score + (current_score - prev_score) * t

            # Calculate team's width
            interp_total_score = total_prev_score + (total_current_score - total_prev_score) * t
            if interp_total_score == 0:
                team_width = 0
            else:
                team_width = (interp_score / interp_total_score) * screen_width

            team['width'] = team_width

            # Draw the rectangle
            pygame.draw.rect(screen, team_color, (x_offset, 0, team_width, screen_height))

            # Try to render the team name within the area
            font_size = MAX_FONT_SIZE
            text_fits = False
            team_text = f"{team_name} {int(current_score)}"

            try:
                while font_size >= MIN_FONT_SIZE:
                    team_font = pygame.font.SysFont(None, font_size)
                    text_surface = team_font.render(team_text, True, (0, 0, 0))

                    # Create text outline
                    outline_surface = create_text_outline(team_font, team_text, (0, 0, 0), (255, 255, 255))

                    text_width, text_height = text_surface.get_size()

                    if text_width <= team_width and text_height <= screen_height:
                        text_fits = True
                        break
                    else:
                        font_size -= 1

                if text_fits:
                    # The text fits, blit it onto the screen
                    text_x = x_offset + (team_width - text_width) / 2
                    text_y = (screen_height - text_height) / 2
                    screen.blit(outline_surface, (text_x, text_y))
                else:
                    # The area is too small, add to small_areas
                    small_areas.append({'name': team_name, 'score': int(current_score)})
            except Exception as e:
                print(f"Error rendering text for team '{team_name}': {e}")

            # Update x_offset
            x_offset += team_width

        # Display scores for teams with small areas in the upper right corner
        score_y = 10
        for team in small_areas:
            score_text = f"{team['name']} {team['score']}"
            text_surface = score_font.render(score_text, True, (255, 255, 255))
            text_width, text_height = text_surface.get_size()
            text_x = screen_width - text_width - 10  # 10 pixels from the right edge
            screen.blit(text_surface, (text_x, score_y))
            score_y += text_height + 5  # Add some spacing

        # Update display
        pygame.display.flip()

        # Check if animation is complete
        if animation_start_time is not None and t >= 1.0:
            animation_start_time = None
            prev_teams = [team.copy() for team in teams]

    pygame.quit()

def create_text_outline(font, message, text_color, outline_color):
    # Render the text multiple times to create an outline
    base = font.render(message, True, text_color)
    outline = pygame.Surface((base.get_width() + 2, base.get_height() + 2), pygame.SRCALPHA)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx != 0 or dy != 0:
                pos = (dx + 1, dy + 1)
                outline.blit(font.render(message, True, outline_color), pos)
    outline.blit(base, (1, 1))
    return outline

def create_team_windows():
    processes = []
    positions = [(50, 50), (400, 50), (50, 500), (400, 500)]  # Positions for windows
    for i in range(len(initial_teams)):
        p = multiprocessing.Process(target=run_team_window, args=(i, positions[i % len(positions)]))
        p.start()
        processes.append(p)
    return processes

def run_team_window(team_index, position):
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{position[0]},{position[1]}"
    pygame.init()
    team_window = pygame.display.set_mode((300, 400), pygame.RESIZABLE)
    pygame.display.set_caption(f"Team {team_index + 1}")

    team = None
    prev_team = None
    prev_percentage = 0
    animation_start_time = None
    animation_duration = 1.0  # Animate over one second
    clock = pygame.time.Clock()
    running = True

    while running:
        dt = clock.tick(60) / 1000.0  # Delta time in seconds

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                # Adjust the window size
                window_width, window_height = event.size
                team_window = pygame.display.set_mode((window_width, window_height), pygame.RESIZABLE)
            else:
                window_width, window_height = team_window.get_size()

        # Read team from JSON file
        try:
            teams = read_teams()
            current_team = teams[team_index]
        except Exception as e:
            print(f"Error reading teams: {e}")
            continue  # Skip this frame

        # Calculate total score
        total_score = sum([max(0, t['score']) for t in teams])
        if total_score == 0:
            total_score = 1  # Avoid division by zero

        # Calculate current percentage
        current_score = max(0, current_team['score'])
        current_percentage = current_score / total_score if total_score > 0 else 0

        # Check if team data has changed
        if team != current_team:
            prev_team = team
            prev_percentage = prev_percentage if team is not None else current_percentage
            team = current_team
            animation_start_time = time.time()
        else:
            # Use previous percentage
            prev_percentage = prev_percentage

        # Calculate animation progress
        if animation_start_time is not None:
            elapsed_time = time.time() - animation_start_time
            t = min(elapsed_time / animation_duration, 1.0)
            interp_percentage = prev_percentage + (current_percentage - prev_percentage) * t
        else:
            t = 1.0
            interp_percentage = current_percentage

        # Draw background
        team_window.fill((0, 0, 0))

        # Calculate fill height
        window_width, window_height = team_window.get_size()
        fill_height = interp_percentage * window_height

        # Draw filled color from bottom to top
        pygame.draw.rect(team_window, team['color'], (0, window_height - fill_height, window_width, fill_height))

        # Render team name and score
        try:
            font = pygame.font.SysFont(None, 48)
            text = f"{team['name']} {int(current_score)}"
            text_surface = font.render(text, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(window_width / 2, window_height / 2))
            team_window.blit(text_surface, text_rect)
        except Exception as e:
            print(f"Error rendering text for team '{team['name']}': {e}")

        # Update display
        pygame.display.flip()

        # Check if animation is complete
        if animation_start_time is not None and t >= 1.0:
            animation_start_time = None
            prev_percentage = current_percentage

    pygame.quit()

def run_pie_chart_window():
    pygame.init()
    pie_window = pygame.display.set_mode((1024, 768), pygame.RESIZABLE)
    pygame.display.set_caption('OB overlay')

    background_color = (0, 255, 255)  # Cyan background

    # Initialize teams
    try:
        teams = read_teams()
    except Exception as e:
        print(f"Error reading teams: {e}")
        return

    running = True
    clock = pygame.time.Clock()

    # Variables to store the current and target angles for animation
    current_angles = [0] * len(teams)
    target_angles = [0] * len(teams)
    animation_speed = 5  # Speed of animation (degrees per frame)

    while running:
        dt = clock.tick(60) / 1000.0  # Delta time in seconds

        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                # Adjust the window size
                pie_window = pygame.display.set_mode(event.size, pygame.RESIZABLE)

        # Read teams from JSON file
        try:
            teams = read_teams()
        except Exception as e:
            print(f"Error reading teams: {e}")
            continue  # Skip this frame

        # Calculate total scores
        total_score = sum([max(0, team['score']) for team in teams])
        if total_score == 0:
            total_score = 1  # Avoid division by zero

        # Calculate target angles for the pie chart
        start_angle = 0
        for i, team in enumerate(teams):
            percentage = max(0, team['score']) / total_score
            target_angles[i] = start_angle + percentage * 360
            start_angle = target_angles[i]

        # Interpolate angles towards target angles for animation
        for i in range(len(current_angles)):
            if current_angles[i] < target_angles[i]:
                current_angles[i] = min(current_angles[i] + animation_speed, target_angles[i])
            elif current_angles[i] > target_angles[i]:
                current_angles[i] = max(current_angles[i] - animation_speed, target_angles[i])

        # Draw background
        pie_window.fill(background_color)

        # Pie chart parameters
        center_x = 300
        center_y = pie_window.get_height() - 300
        radius = 200

        start_angle = 0

        # Draw pie chart with animated angles
        for i, team in enumerate(teams):
            end_angle = current_angles[i]

            # Draw pie slice
            pygame.draw.arc(pie_window, team['color'], (center_x - radius, center_y - radius, 2 * radius, 2 * radius),
                            math.radians(start_angle), math.radians(end_angle), radius)
            pygame.draw.line(pie_window, team['color'], (center_x, center_y),
                             (center_x + radius * math.cos(math.radians(start_angle)),
                              center_y + radius * math.sin(math.radians(start_angle))), 2)
            pygame.draw.line(pie_window, team['color'], (center_x, center_y),
                             (center_x + radius * math.cos(math.radians(end_angle)),
                              center_y + radius * math.sin(math.radians(end_angle))), 2)

            # Display team name and score, only if score is greater than 0
            if team['score'] > 0:
                font = pygame.font.SysFont(None, 36)
                text = f"{team['name']} {team['score']}"
                text_surface = create_text_outline(font, text, (0, 0, 0), (255, 255, 255))
                text_x = center_x + (radius + 30) * math.cos(math.radians((start_angle + end_angle) / 2))
                text_y = center_y + (radius + 30) * math.sin(math.radians((start_angle + end_angle) / 2))

                # Avoid placing text too close to the edge
                text_rect = text_surface.get_rect(center=(text_x, text_y))
                pie_window.blit(text_surface, text_rect)

            # Update start angle
            start_angle = end_angle

        # Update display
        pygame.display.flip()

    pygame.quit()

def start_sacn_sender():
    config = read_config()
    sender = sACNsender()
    sender.start()
    sender.activate_output(1)
    sender[1].multicast = False  # Set to unicast mode
    sender[1].destination = config['sacn_ip']  # Use IP from config
    return sender

def update_sacn():
    sender = start_sacn_sender()
    teams = read_teams()

    dmx_data = [0] * 133 * 3  # Initialize DMX data for 133 pixels

    # Define segments for sACN
    segments = [
        {'start': 1, 'stop': 36, 'color': teams[0]['color']},
        {'start': 37, 'stop': 65, 'color': teams[1]['color']},
        {'start': 66, 'stop': 90, 'color': teams[2]['color']},
        {'start': 91, 'stop': 133, 'color': teams[3]['color']}
    ]

    total_score = sum([team['score'] for team in teams]) or 1  # Prevent division by zero
    for i, segment in enumerate(segments):
        segment_score = teams[i]['score']
        percent_on = segment_score / total_score

        if percent_on > 0.50:  # If more than 50% of the total score, turn on the whole segment
            percent_on = 1.0
        else:
            percent_on = percent_on * 2

        num_pixels_on = int(percent_on * (segment['stop'] - segment['start']))

        for pixel in range(segment['start'] - 1, segment['start'] - 1 + num_pixels_on):
            dmx_data[pixel * 3:pixel * 3 + 3] = segment['color']

    # Send sACN data
    sender[1].dmx_data = dmx_data
    time.sleep(0.05)  # Wait briefly to ensure data is sent
    sender.stop()  # Stop sender

# Function to play the appropriate sound effect
def play_sound_effect(action):
    try:
        if action > 0:
            sound = pygame.mixer.Sound(sound_effect_file_add)
        else:
            sound = pygame.mixer.Sound(sound_effect_file_subtract)
        sound.play()
        # Wait until the sound has finished playing before returning
        while pygame.mixer.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print(f"Error playing sound effect: {e}")

# Function to announce score change using gTTS
def announce_score_change(team_name, score_change):
    if score_change > 0:
        message = f"{team_name} gained {score_change} point{'s' if score_change > 1 else ''}."
    elif score_change < 0:
        message = f"{team_name} lost {abs(score_change)} point{'s' if abs(score_change) > 1 else ''}."
    else:
        return  # No change

    try:
        # Generate speech using gTTS
        tts = gTTS(text=message, lang='en')
        # Save to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            temp_filename = fp.name
            tts.save(temp_filename)
        # Play the MP3 file using pygame.mixer.music
        pygame.mixer.music.load(temp_filename)
        pygame.mixer.music.play()
        # Wait until playback is finished
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        # Delete the temporary file
        os.remove(temp_filename)
    except Exception as e:
        print(f"Error with TTS: {e}")

# Function to announce individual team score using gTTS
def announce_team_score(team):
    message = f"{team['name']} has {team['score']} point{'s' if team['score'] != 1 else ''}."
    try:
        tts = gTTS(text=message, lang='en')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            temp_filename = fp.name
            tts.save(temp_filename)
        pygame.mixer.music.load(temp_filename)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        os.remove(temp_filename)
    except Exception as e:
        print(f"Error with TTS: {e}")

# Function to announce all team scores using gTTS
def announce_all_scores(teams):
    messages = [f"{team['name']} has {team['score']} point{'s' if team['score'] != 1 else ''}." for team in teams]
    message = " ".join(messages)
    try:
        tts = gTTS(text=message, lang='en')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            temp_filename = fp.name
            tts.save(temp_filename)
        pygame.mixer.music.load(temp_filename)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        os.remove(temp_filename)
    except Exception as e:
        print(f"Error with TTS: {e}")

if __name__ == '__main__':
    multiprocessing.freeze_support()  # For Windows support
    initialize_teams()  # Ensure teams.json is initialized

    # Start Flask app in a separate thread
    flask_thread = create_flask_thread()

    # Start team windows in separate processes
    team_processes = create_team_windows()

    # Start pie chart window in a separate process
    pie_chart_process = multiprocessing.Process(target=run_pie_chart_window)
    pie_chart_process.start()

    # Run main Pygame app
    run_main_pygame()

    # Terminate team windows when main window is closed
    for p in team_processes:
        p.terminate()
    for p in team_processes:
        p.join()

    # Terminate pie chart window
    pie_chart_process.terminate()
    pie_chart_process.join()

    # Quit Pygame mixer
    pygame.mixer.quit()
