import logging
import os

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    logger.warning("boto3 not installed — admin Cognito operations disabled")


def admin_confirm_sign_up(email: str) -> bool:
    if not HAS_BOTO3:
        logger.warning("boto3 unavailable, cannot auto-confirm user")
        return False

    pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
    region = os.getenv("COGNITO_REGION", "eu-north-1")
    if not pool_id:
        logger.warning("COGNITO_USER_POOL_ID not set")
        return False

    try:
        client = boto3.client("cognito-idp", region_name=region)
        client.admin_confirm_sign_up(
            UserPoolId=pool_id,
            Username=email,
        )
        logger.info(f"Auto-confirmed user: {email}")
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "UserNotFoundException":
            logger.warning(f"User not found: {email}")
        elif code == "NotAuthorizedException":
            logger.warning(f"Not authorized to confirm user (check IAM permissions): {email}")
        elif code == "InvalidParameterException":
            logger.warning(f"Invalid parameter for user: {email}")
        else:
            logger.error(f"Cognito admin error for {email}: {code} - {e}")
        return False
    except NoCredentialsError:
        logger.warning("No AWS credentials found for admin_confirm_sign_up")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error confirming user {email}")
        return False


def admin_create_user(email: str, password: str) -> tuple[bool, str | dict]:
    """Create a user in Cognito and set a permanent password.

    Returns (True, AuthenticationResult dict) on success,
    or (False, error_message) on failure.
    """
    if not HAS_BOTO3:
        return False, "boto3 not available"

    pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
    region = os.getenv("COGNITO_REGION", "eu-north-1")
    if not pool_id:
        return False, "Cognito not configured (COGNITO_USER_POOL_ID missing)"

    try:
        client = boto3.client("cognito-idp", region_name=region)

        # Create the user
        client.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )

        # Set permanent password
        client.admin_set_user_password(
            UserPoolId=pool_id,
            Username=email,
            Password=password,
            Permanent=True,
        )

        # Sign in to get tokens
        client_id = os.getenv("COGNITO_CLIENT_ID", "")
        if not client_id:
            return False, "COGNITO_CLIENT_ID not set"

        resp = client.admin_initiate_auth(
            UserPoolId=pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password,
            },
        )
        result = resp.get("AuthenticationResult", {})
        if result:
            return True, result
        return False, "No AuthenticationResult in response"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"].get("Message", code)
        if code == "UsernameExistsException":
            return False, "An account with this email already exists"
        logger.warning(f"admin_create_user failed for {email}: {code} - {msg}")
        return False, msg
    except NoCredentialsError:
        logger.warning("No AWS credentials found for admin_create_user")
        return False, "AWS credentials not configured"
    except Exception as e:
        logger.exception(f"Unexpected error in admin_create_user for {email}")
        return False, str(e)


def admin_sign_in(email: str, password: str) -> tuple[bool, str | dict]:
    """Sign in using AdminInitiateAuth — bypasses user confirmation check."""
    if not HAS_BOTO3:
        return False, "boto3 not available"

    pool_id = os.getenv("COGNITO_USER_POOL_ID", "")
    client_id = os.getenv("COGNITO_CLIENT_ID", "")
    region = os.getenv("COGNITO_REGION", "eu-north-1")
    if not pool_id or not client_id:
        return False, "Cognito not configured (COGNITO_USER_POOL_ID or COGNITO_CLIENT_ID missing)"

    try:
        client = boto3.client("cognito-idp", region_name=region)
        resp = client.admin_initiate_auth(
            UserPoolId=pool_id,
            ClientId=client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password,
            },
        )
        result = resp.get("AuthenticationResult", {})
        if result:
            return True, result
        return False, "No AuthenticationResult in response"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = e.response["Error"].get("Message", code)
        logger.warning(f"admin_sign_in failed for {email}: {code} - {msg}")
        return False, msg
    except NoCredentialsError:
        logger.warning("No AWS credentials found for admin_sign_in")
        return False, "AWS credentials not configured"
    except Exception as e:
        logger.exception(f"Unexpected error in admin_sign_in for {email}")
        return False, str(e)
