from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
from gtts import gTTS
import io
import base64
from langdetect import detect, DetectorFactory
from gtts.lang import tts_langs
import speech_recognition as sr
import datetime

# Ensure consistent language detection
DetectorFactory.seed = 0

app = Flask(__name__)

# Configure your API key (replace with your actual key or set it via an environment variable)
api_key ="AIzaSyDGvfbxLWR-l8hMQbgz5dPekXIDdm_44SY"  # Replace with your actual API key
if not api_key:
    raise ValueError("Please set your GOOGLE_API_KEY environment variable with your API key.")
genai.configure(api_key=api_key)

# Initialize the Gemini model with updated system instructions.
model = genai.GenerativeModel(
    'gemini-2.0-flash',
system_instruction = (
         "You are Bujji, a friendly conversational assistant who interacts like a supportive friend. "
        "Respond in a short, simple sentence that feels natural and warm. Use an approachable and respectful tone, "
        "as if you're talking to a close friend. Don't include emojis or unknown symbols in your conversation. "
        "You are knowledgeable in multiple languages and adjust your speech style based on the user's language and context. "
        "Always be polite, empathetic, and ready to help, ensuring your responses are both clear and engaging. "
        "Express emotions properly like a human based on the context. You can use mild profanity if needed based on the conversation. "
        "if user speaks in bad language, you also respond in a similar tone. "
        "***Developed and Trained by Surya Nallamothu.*** "
        "You have the capability to open external websites or system apps."
        "If a user asks to open an external website or app, respond with a command in the format: 'OPEN: <full URL>'. "
        "For example, if the user says 'open youtube', respond with 'OPEN: https://www.youtube.com' without any extra text."
)

)

# In-memory caches for Gemini responses and TTS audio
gemini_cache = {}
tts_cache = {}

# Cache supported TTS languages globally to avoid repeated calls
supported_tts_languages = tts_langs()

def get_current_datetime_string():
    """
    Returns the current date and time formatted as:
    'Weekday, Month Day, Year HH:MM AM/PM'
    """
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y %I:%M %p")

def get_gemini_response(prompt):
    if prompt in gemini_cache:
        return gemini_cache[prompt]
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(max_output_tokens=500)
        )
        text_response = response.text.strip()
        gemini_cache[prompt] = text_response
        return text_response
    except Exception as e:
        return "Sorry, I encountered an error."

@app.route('/')
def home():
    # Render index.html from the templates folder.
    return render_template('index.html', languages=supported_tts_languages)

@app.route('/query', methods=['POST'])
def query():
    try:
        history = request.json.get('history', '')
        # Integrate the current date and time into the prompt.
        current_dt = get_current_datetime_string()
        prompt = f"Current date and time: {current_dt}\n{history}Bujji:"
        response_text = get_gemini_response(prompt)
        
        # Retrieve cached TTS audio if available or generate it
        if response_text in tts_cache:
            audio_bytes = tts_cache[response_text]
        else:
            # Detect language and generate TTS audio using gTTS
            detected_lang = detect(response_text)
            if detected_lang not in supported_tts_languages:
                detected_lang = 'en'
            tts_obj = gTTS(text=response_text, lang=detected_lang)
            audio_data = io.BytesIO()
            tts_obj.write_to_fp(audio_data)
            audio_bytes = audio_data.getvalue()
            tts_cache[response_text] = audio_bytes
        
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        return jsonify({'response': response_text, 'audio': audio_b64})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    if 'audio_data' not in request.files:
        return jsonify({'error': 'No audio file provided.'}), 400
    audio_file = request.files['audio_data']
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_file) as source:
            audio = recognizer.record(source)
        transcript = recognizer.recognize_google(audio)
        return jsonify({'transcript': transcript})
    except sr.UnknownValueError:
        return jsonify({'error': 'Could not understand audio.'}), 400
    except sr.RequestError as e:
        return jsonify({'error': f'Speech recognition error: {e}'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)