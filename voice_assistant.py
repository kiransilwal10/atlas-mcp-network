import os
import subprocess
import requests
import speech_recognition as sr 
from openai import OpenAI
from elevenlabs.client import ElevenLabs
from elevenlabs import play
from dotenv import load_dotenv


load_dotenv()

#initialise API clients
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
eleven_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

GATEWAY_URL = "http://127.0.0.1:8000/agent/chat"

def listen_to_microphone():
    #record audio from the microphone and use whisper to get perfect text
    recognizer = sr.Recognizer()

    #increase pause threshold from 0.8s to 2.5s
    recognizer.pause_threshold = 2.5

    with sr.Microphone() as source:
        print("Listening..Speak your command, lord kiran!")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)
    
    try:
        print("Processing speech ...")
        text = recognizer.recognize_google(audio)
        return text
    
    except Exception as e:
        print(f"Failed to transcribe audio: {e}")
        return None
    
def speak_response(text):
    """
    take claude's text answer and convert it into high-quality spoken audio
    """
    if not text:
        return
    
    try:
        print("Generating voice response...")
        audio = eleven_client.text_to_speech.convert(
            text = text,
            voice_id="JBFqnCBsd6RMkjVDRZzb",  
            model_id="eleven_multilingual_v2"
        )
        play(audio)
    except Exception as e:
        print(f"Voice synthesis failed: {e}")
        
        #secure fallback
        subprocess.run(["say", text])

def main():
    print("=== Personal MCP Voice Assistant Activated ===")

    while True:
        #listen to the user
        user_text = listen_to_microphone()

        if not user_text:
            continue
        
        #clean up string
        clean_text = user_text.strip().lower()

        #check for exit commands
        if any(word in clean_text for word in ["exit", "quit", "stop assistant", "bye"]):
            print("Shutting down assistant. Goodbye!")
            break

        print(f" You said: \"{user_text}\"")

        #forward the text to the FastAPI MCP Gateway
        try:
            response = requests.post(GATEWAY_URL, json={"prompt": user_text })
            response_data = response.json()
            claude_response = response_data.get("agent_response", "")

            print(f" Claude: {claude_response}")

            #read claude's answer back out loud
            speak_response(claude_response)

        except Exception as e:
            print(f"Gateway communication error: {e}")

if __name__ == "__main__":
    main()

                  
                  
                
        





    



              
