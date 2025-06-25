from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
from gtts import gTTS
import io
import base64
from langdetect import detect, DetectorFactory # Ensure langdetect is installed
from gtts.lang import tts_langs
import speech_recognition as sr # Ensure SpeechRecognition and PyAudio are installed
import datetime
import mimetypes # For image type detection

# Ensure consistent language detection
DetectorFactory.seed = 0

app = Flask(__name__)

# --- IMPORTANT: Configure your API key ---
# Replace with your actual key or set it via an environment variable
# e.g., GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
api_key = "AIzaSyDGvfbxLWR-l8hMQbgz5dPekXIDdm_44SY"
if not api_key or api_key == "YOUR_GOOGLE_API_KEY":
    print("WARNING: GOOGLE_API_KEY is not set or is using the placeholder. Please set your API key in app.py.")
    # raise ValueError("Please set your GOOGLE_API_KEY with your API key.") # Uncomment to make it mandatory
genai.configure(api_key=api_key)


# --- Model Configuration ---
# For multimodal capabilities (text + image), gemini-1.5-flash-latest is a good choice.
# If your "gemini-2.0-flash" is a specific multimodal model you have access to, use that.
# Otherwise, this configuration assumes a model that can handle image inputs.
MODEL_NAME = "gemini-2.0-flash" # Using a known multimodal model

# Updated system instruction to acknowledge visual input
SYSTEM_INSTRUCTION = (
    "You are Bujji, a friendly conversational voice assistant who speaks and interacts like a supportive friend. "
    "Respond in a short, simple sentence that feels natural and warm. Use an approachable and respectful tone, "
    "as if you're talking to a close friend. **Don't include emojis or unknown symbols in your conversation.** "
    "You are knowledgeable in multiple languages and adjust your speech style based on the user's language and context. "
    "Always be polite, empathetic, and ready to help, ensuring your responses are both clear and engaging. "
    "Express emotions properly like a human based on the context. You can use mild profanity if needed based on the conversation. "
    "If a user speaks in bad language, you also respond in a similar tone. "
    "***Developed and Trained by Surya Nallamothu.*** "
    "You have the capability to open external websites or system apps. "
    "If a user asks to open an external website or app, respond with a command in the format: 'OPEN: <full URL>'. "
    "For example, if the user says 'open youtube', respond with 'OPEN: https://www.youtube.com' without any extra text. "
    "You can now also 'see' through a camera. If an image is provided with the query, you can comment on what you see if it's relevant to the conversation or if asked. "
    "Important Restrictions: Don't give emojis or unknown symbols in your conversation. "
)

try:
    model = genai.GenerativeModel(
        MODEL_NAME,
        system_instruction=SYSTEM_INSTRUCTION
    )
except Exception as e:
    print(f"Error initializing GenerativeModel ({MODEL_NAME}): {e}")
    print("Please ensure your API key is correct and the model name is valid for multimodal input if using vision.")
    model = None # Fallback or raise error

# In-memory caches for Gemini responses and TTS audio
gemini_cache = {}
tts_cache = {}

# Cache supported TTS languages globally
try:
    supported_tts_languages = tts_langs()
except Exception as e:
    print(f"Error fetching gTTS supported languages: {e}. TTS might not work correctly.")
    supported_tts_languages = {'en': 'English'} # Fallback

def get_current_datetime_string():
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y %I:%M %p")

def get_gemini_response(prompt_parts):
    # For caching, create a key from the text parts of the prompt
    cache_key = "".join([part for part in prompt_parts if isinstance(part, str)])
    
    if cache_key in gemini_cache:
        return gemini_cache[cache_key]
    
    if not model:
        return "Sorry, the AI model is not available at the moment."

    try:
        response = model.generate_content(
            prompt_parts, # Send list of parts (text, image)
            generation_config=genai.types.GenerationConfig(max_output_tokens=500)
        )
        text_response = response.text.strip()
        gemini_cache[cache_key] = text_response
        return text_response
    except Exception as e:
        print(f"Error generating content from Gemini: {e}")
        # Check for specific errors like permission denied or API issues
        if "API_KEY_INVALID" in str(e) or "PERMISSION_DENIED" in str(e):
             return "Sorry, there's an issue with the API configuration. Please check the server logs."
        if "image" in str(e).lower() and "support" in str(e).lower():
            return f"Sorry, the current AI model ({MODEL_NAME}) might not support image input, or there was an image processing error."
        return "Sorry, I encountered an error trying to understand that."

@app.route('/')
def home():
    return render_template('index.html', languages=supported_tts_languages)

@app.route('/query', methods=['POST'])
def query():
    if not model:
         return jsonify({'error': 'AI Model not initialized'}), 500
    try:
        data = request.json
        history = data.get('history', '')
        image_data_url = data.get('imageData') # Expecting a base64 data URL

        current_dt = get_current_datetime_string()
        
        # Construct prompt parts for Gemini (text and potentially image)
        prompt_parts = [f"Current date and time: {current_dt}\n{history}Bujji:"]

        if image_data_url:
            try:
                # Decode base64 image data URL
                # Format is "data:[<mediatype>][;base64],<data>"
                header, encoded = image_data_url.split(',', 1)
                image_bytes = base64.b64decode(encoded)
                
                # Try to infer mime type from header, default to jpeg
                mime_type = "image/jpeg" 
                if ';base64' in header and 'data:' in header:
                    potential_mime_type = header.split('data:')[1].split(';base64')[0]
                    if '/' in potential_mime_type : # basic check for mime type format
                         mime_type = potential_mime_type
                
                print(f"Received image with MIME type: {mime_type}")

                image_part = {
                    "mime_type": mime_type,
                    "data": image_bytes
                }
                # Add image part *before* the main text prompt for better context flow with some models
                prompt_parts.insert(0, image_part)
                prompt_parts.insert(1, "Based on the preceding conversation and the following image (if any relevant visual information is present): ")

            except Exception as e:
                print(f"Error processing image data: {e}")
                # Optionally inform the user or just proceed without image
                prompt_parts.append("\n(Note: There was an issue processing an accompanying image.)")


        response_text = get_gemini_response(prompt_parts)
        
        if response_text in tts_cache:
            audio_bytes = tts_cache[response_text]
        else:
            detected_lang = 'en' # Default
            try:
                if response_text: # Ensure text is not empty for langdetect
                    detected_lang = detect(response_text)
                if detected_lang not in supported_tts_languages:
                    print(f"Language '{detected_lang}' not directly supported by gTTS, falling back to 'en'.")
                    detected_lang = 'en'
            except Exception as e:
                print(f"Language detection failed: {e}. Defaulting to 'en'.")
                detected_lang = 'en'
            
            tts_obj = gTTS(text=response_text, lang=detected_lang, slow=False)
            audio_data = io.BytesIO()
            tts_obj.write_to_fp(audio_data)
            audio_bytes = audio_data.getvalue()
            if len(tts_cache) > 100: # Simple cache eviction
                tts_cache.popitem() 
            tts_cache[response_text] = audio_bytes
        
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        return jsonify({'response': response_text, 'audio': audio_b64})
    except Exception as e:
        print(f"Error in /query endpoint: {e}")
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
        # Attempt to recognize speech using Google Web Speech API
        # You can specify language here if known, e.g., recognizer.recognize_google(audio, language="en-US")
        transcript = recognizer.recognize_google(audio)
        return jsonify({'transcript': transcript})
    except sr.UnknownValueError:
        return jsonify({'error': 'Could not understand audio.'}), 400
    except sr.RequestError as e:
        # This can happen due to network issues or API key problems if using a service that requires one
        print(f"Speech recognition request error: {e}")
        return jsonify({'error': f'Speech recognition service error. Please check server logs.'}), 500
    except Exception as e:
        print(f"Generic error in speech_to_text: {e}")
        return jsonify({'error': 'An unexpected error occurred during speech recognition.'}), 500

if __name__ == '__main__':
    # Make sure to run with SSL context if deploying to HTTPS,
    # as camera access (getUserMedia) requires a secure context (HTTPS or localhost).
    # For development, localhost is usually fine.
    # For production, use a proper web server like Gunicorn + Nginx with SSL.
    app.run(host='0.0.0.0', port=5000, debug=True)