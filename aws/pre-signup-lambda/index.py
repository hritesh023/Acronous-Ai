import json

def lambda_handler(event, context):
    """Auto-confirm every user who signs up — no verification code needed."""
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = True
    event["response"]["autoVerifyPhone"] = True
    return event
