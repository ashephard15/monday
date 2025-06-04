import boto3
import json
import traceback
from datetime import datetime, timedelta
import random

# --- Helper Functions ---
def supports_apl(event):
    try:
        return event['context']['System']['device']['supportedInterfaces']['Alexa.Presentation.APL']
    except KeyError:
        return False

def parse_date(date_string):
    try:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    except ValueError:
        return None

def update_streak(user_id):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('monday_streak_tracker')
    today = datetime.utcnow().date()
    today_str = today.isoformat()

    try:
        response = table.get_item(Key={'userId': user_id})
        item = response.get('Item', {})
        last_check_str = item.get('lastCheck', None)
        streak = item.get('streak', 0)
        streak_increased = False 

        if last_check_str:
            last_date = parse_date(last_check_str)
            if last_date is None: 
                streak = 1
                streak_increased = True
            elif today == last_date:
                return streak, False, "already"
            elif today == last_date + timedelta(days=1):
                streak += 1
                streak_increased = True
            else: 
                streak = 1
                streak_increased = True
        else: 
            streak = 1
            streak_increased = True

        table.put_item(Item={
            'userId': user_id,
            'lastCheck': today_str,
            'streak': streak
        })
        return streak, streak_increased, None 
    except Exception as e:
        print(f"STREAK ERROR for user {user_id}: {traceback.format_exc()}")
        return 0, False, "error"

def select_speech_response(streak, returned_message_key):
    voice_tag_open = "<voice name='Joanna'>"
    voice_tag_close = "</voice>"
    
    # Standard rate for most responses, can be "medium", "fast", or "+10%", etc.
    # Let's try "medium" to ensure a natural pace, not too slow.
    # If still too slow, we can change this to "fast" or a percentage increase.
    normal_rate_prosody_open = "<prosody rate='medium'>"
    normal_rate_prosody_close = "</prosody>"

    if returned_message_key == "already":
        moods = ["playful", "annoyed", "tired"]
        mood = random.choice(moods)
        if mood == "playful":
            speech = "Well, bless your heart, looks like you already moseyed on in today! No need to show off now, we gotcha down!"
            return f"<speak>{voice_tag_open}{speech}{voice_tag_close}</speak>", True
        elif mood == "annoyed":
            # This mood is intentionally slower
            speech = "<prosody rate='medium' pitch='-2%'>Welp. Looks like you already checked in, again. Yep. Good for you!</prosody>"
            return f"<speak>{voice_tag_open}{speech}{voice_tag_close}</speak>", True
        elif mood == "tired": 
            # This mood is intentionally much slower
            speech = "<prosody rate='medium' pitch='-4%'>Goodness gracious... you're already in the system for today, hon. Why don't ya rest those boots a spell?</prosody>"
            return f"<speak>{voice_tag_open}{speech}{voice_tag_close}</speak>", True

    if returned_message_key == "error":
        speech = "Shootfire! Somethin' went a bit sideways there. Ol' Monday's fixin' to take a gander at what went wrong, don't you worry."
        return f"<speak>{voice_tag_open}{normal_rate_prosody_open}{speech}{normal_rate_prosody_close}{voice_tag_close}</speak>", True

    # Normal streak updates with normal_rate_prosody
    if streak == 1:
        speech = "Well howdy! Glad to see ya back. You just kicked off a new streak, so let's see if we can keep this wagon rollin', alright now?"
        return f"<speak>{voice_tag_open}{normal_rate_prosody_open}{speech}{normal_rate_prosody_close}{voice_tag_close}</speak>", False
    elif streak > 0 and streak < 5:
        speech = f"Well, I'll be! That's a {streak}-day streak you got goin'! You're doin' alright, partner. Keep it shinin'!"
        return f"<speak>{voice_tag_open}{normal_rate_prosody_open}{speech}{normal_rate_prosody_close}{voice_tag_close}</speak>", False
    elif streak >= 5:
        speech = f"Hot diggity dog! A {streak}-day streak! Why, Monday's grinnin' like a possum eatin' a sweet tater. Mighty fine job, y'hear?"
        return f"<speak>{voice_tag_open}{normal_rate_prosody_open}{speech}{normal_rate_prosody_close}{voice_tag_close}</speak>", False
    else: 
        speech = "Well now, Monday's scratchin' its head a bit over this here streak business. Not quite sure what to make of it, friend."
        return f"<speak>{voice_tag_open}{normal_rate_prosody_open}{speech}{normal_rate_prosody_close}{voice_tag_close}</speak>", False

# --- Lambda Handler ---
def lambda_handler(event, context):
    print("EVENT:", json.dumps(event, indent=2))
    try:
        request_type = event['request']['type']

        if request_type == "SessionEndedRequest":
            if event['request'].get('reason') == 'ERROR':
                print(f"SessionEndedRequest due to ERROR: {json.dumps(event['request'].get('error'))}")
            else:
                print("Session ended. No response necessary.")
            return {'version': '1.0', 'response': {}}

        user_id = event.get('session', {}).get('user', {}).get('userId')
        if not user_id:
            user_id = event.get('context', {}).get('System', {}).get('user', {}).get('userId', 'anonymous_user')
            if user_id == 'anonymous_user':
                print("Warning: Could not determine a unique user ID.")
        
        streak, streak_increased, returned_message_key = update_streak(user_id)
        
        print(f"Streak: {streak}, Increased: {streak_increased}, MessageKey: {returned_message_key}")

        speech_output_ssml, final_should_end_session = select_speech_response(streak, returned_message_key)

        reprompt_speech_ssml = None
        if not final_should_end_session:
            # Using Joanna voice and normal rate for reprompt as well
            reprompt_speech_ssml = "<speak><voice name='Joanna'><prosody rate='medium'>Anything else I can wrangle up for ya, or are we all set for now?</prosody></voice></speak>"

        alexa_response_payload = {
            'shouldEndSession': final_should_end_session,
            'outputSpeech': {
                'type': 'SSML',
                'ssml': speech_output_ssml
            },
            'directives': []
        }

        if reprompt_speech_ssml:
            alexa_response_payload['reprompt'] = {
                'outputSpeech': {
                    'type': 'SSML',
                    'ssml': reprompt_speech_ssml
                }
            }

        if supports_apl(event):
            apl_directive = {
                'type': 'Alexa.Presentation.APL.RenderDocument',
                'token': 'mondayAvatarToken',
                'document': {
                    'type': 'APL',
                    'version': '1.1', 
                    'mainTemplate': {
                        'parameters': ['payload'],
                        'items': [
                            { 
                                'type': 'Container',
                                'width': '100vw',
                                'height': '100vh',
                                'items': [
                                    { 
                                        'type': 'Image',
                                        'source': 'https://monday-avatar-angela.s3.us-east-1.amazonaws.com/monday-avatar.jpeg',
                                        'scale': 'best-fit',
                                        'width': '100vw',
                                        'height': '100vh',
                                        'align': 'left' 
                                    },
                                    { 
                                        'type': 'Container',
                                        'position': 'absolute',
                                        'left': '425dp', 
                                        'top': '40dp',
                                        'alignItems': 'flex-start', 
                                        'items': [
                                            { 
                                                'type': 'Text',
                                                'text': "${payload.meter.level > 3 ? '🔥 Certified Icon' : '💤 Low Vibes'}",
                                                'fontSize': '40dp',
                                                'color': "${payload.meter.level > 3 ? '#FF69B4' : '#00BFFF'}",
                                                'fontWeight': 'bold',
                                                'textAlign': 'right' 
                                            },
                                            { 
                                                'type': 'Container',
                                                'paddingTop': '10dp',     
                                                'direction': 'row',      
                                                'spacing': '10dp',       
                                                'items': [
                                                    {
                                                        'type': 'Frame', 'height': '80dp', 'width': '80dp',
                                                        'backgroundColor': "${payload.meter.level >= 1 ? '#FF69B4' : '#666'}",
                                                        'borderRadius': '10dp', 'borderWidth': '2dp', 'borderColor': '#00BFFF'
                                                    },
                                                    {
                                                        'type': 'Frame', 'height': '80dp', 'width': '80dp',
                                                        'backgroundColor': "${payload.meter.level >= 2 ? '#FF69B4' : '#666'}",
                                                        'borderRadius': '10dp', 'borderWidth': '2dp', 'borderColor': '#00BFFF'
                                                    },
                                                    {
                                                        'type': 'Frame', 'height': '80dp', 'width': '80dp',
                                                        'backgroundColor': "${payload.meter.level >= 3 ? '#FF69B4' : '#666'}",
                                                        'borderRadius': '10dp', 'borderWidth': '2dp', 'borderColor': '#00BFFF'
                                                    },
                                                    { 
                                                        'type': 'Frame', 'height': '80dp', 'width': '80dp',
                                                        'backgroundColor': "${payload.meter.level >= 4 ? '#FF69B4' : '#666'}",
                                                        'borderRadius': '10dp', 
                                                        'borderWidth': '2dp', 'borderColor': '#00BFFF'
                                                    }
                                                ]
                                            },
                                            { 
                                                'type': 'Text',
                                                'text': "Unstoppable. Unbothered. Possibly Caffeinated.",
                                                'color': '#FF69B4',
                                                'fontSize': '22dp',
                                                'fontWeight': '700',
                                                'paddingTop': '80dp', 
                                                'textAlign': 'right' 
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                },
                'datasources': {
                    'payload': {
                        'meter': {
                            'level': streak 
                        }
                    }
                }
            }
            alexa_response_payload['directives'].append(apl_directive)
        
        return {
            'version': '1.0',
            'response': alexa_response_payload
        }

    except Exception as e:
        print(f"LAMBDA ERROR: {traceback.format_exc()}") 
        return {
            'version': '1.0',
            'response': {
                'shouldEndSession': True,
                'outputSpeech': {
                    'type': 'PlainText',
                    'text': "Something exploded. Monday is reviewing the damage."
                }
            }
        }