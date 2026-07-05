"""LiveKit service — generate tokens for video/audio rooms."""

from livekit import api


def generate_livekit_token(
    room_name: str,
    participant_name: str,
    api_key: str,
    api_secret: str,
) -> str:
    """Generate a LiveKit access token for a participant to join a room."""
    token = api.AccessToken(api_key, api_secret)
    token.with_identity(participant_name)
    token.with_name(participant_name)
    token.with_grants(api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
    ))
    return token.to_jwt()
