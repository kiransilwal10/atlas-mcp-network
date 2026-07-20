import os
import requests
import speech_recognition as sr 
from openai import OpenAI
from elevenlabs.client import ElevenLabs
from elevenlabs import play
from dotenv import load_dotenv

load_dotenv()

#initialise API clients
openai_clients = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
eleven_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

GATEWAY_URL = "http://127.0.0.1:8000/agent/chat"

def listen_to_microphone():
    #record audio from the microphone and use whisper to get perfect text
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening..Speak your command, lord kiran!")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        audio = recognizer.listen(source)
    
    try:
        print("Processing speech ...")
        #save audio temporaarily to send to whisper
        with open("temp_audio.wav", "wb") as f:
            f.write(audio.get_wav_data())

        with open("temp_audio.wav") as audio_file: 
            transcript 


              
