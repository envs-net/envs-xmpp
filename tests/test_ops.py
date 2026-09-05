from envs_xmpp_ops.deploy import resolve_paths
from envs_xmpp_ops.profile import DeploymentProfile


def test_profile_paths():
    profile = DeploymentProfile(
        app_name="bot",
        executable="bot",
        service_name="bot.service",
        config_environment="BOT_CONFIG",
        default_config="/etc/bot/config.py",
        default_data="/var/lib/bot",
        service_user="bot",
        service_group="bot",
        venv_name="venv",
    )
    paths = resolve_paths("/srv/bot", profile)
    assert str(paths.venv) == "/srv/bot/venv"
    assert str(paths.config) == "/etc/bot/config.py"
