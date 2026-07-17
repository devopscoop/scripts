# AWS tools

## Install required packages

This repo ships package manifests that install every CLI tool its scripts use (`age`, `aws`, `aws-sso`, `bash`, `checkov`, `curl`, `gh`, `gpg`, `jq`, `python3`, `saml2aws`, `tenv` for `tofu`, `trivy`):

- macOS, using [Homebrew](https://brew.sh/) and the `Brewfile`:

  ```shell
  brew bundle
  ```

- Arch Linux, using the `pkglist.txt`. This requires an AUR helper such as [yay](https://github.com/Jguer/yay) or [paru](https://github.com/Morganamilo/paru), because `aws-sso-cli-bin`, `saml2aws`, and `tenv-bin` are AUR packages. `checkov` isn't packaged for Arch at all — install it with `uv tool install checkov` or `pipx install checkov`:

  ```shell
  grep -vE '^(#|$)' pkglist.txt | yay -S --needed -
  ```

On other operating systems, install the tools listed above manually.

The Python scripts also need libraries that package managers don't provide: `pip install caldav ruamel.yaml`.

## saml2aws

Here are two helper scripts for saml2aws.

### saml2aws_configure.sh

Run this script once with your Okta username, password, and Okta Amazon AWS URL like this:

```
SAML2AWS_USERNAME=your_Okta_username SAML2AWS_PASSWORD=your_Okta_password okta_url=your_Okta_amazon_aws_url ./saml2aws_configure.sh
```

This will create a `~/.saml2aws` file with sane defaults and DUO MFA.

### saml2aws_login.sh

Run this script daily to log you into all possible combinations of AWS account and role, and create AWS Profiles for each of them with the naming scheme `${account}_${role}`.

## Deprecated

### aws_configure_all_sso.sh (Deprecated)

> Deprecated: Use [aws-sso-cli](https://github.com/synfinatic/aws-sso-cli) instead.

This configures all of your AWS IAM Identity Center (SSO) account and role combinations, so you don't have to loop through `aws configure sso` dozens of times, or copy-paste a bunch of junk in your ~/.aws/config. Here is example usage:

```
[evans@archlinux ~]$ ./aws_configure_all_sso.sh

ERROR: You must specify your start URL prefix and region like this:

./aws_configure_all_sso.sh start_url_prefix aws_region

Example:

./aws_configure_all_sso.sh mycompany us-west-2

[evans@archlinux ~]$ ./aws_configure_all_sso.sh mycompany us-west-2
Warning: Input is not a terminal (fd=0).
SSO session name: mycompany
SSO start URL [None]: https://mycompany.awsapps.com/start
SSO region [None]: us-west-2
SSO registration scopes [sso:account:]: sso:account:

Completed configuring SSO session: mycompany
Run the following to login and refresh  token for this session:

aws sso login --sso-session mycompany
Attempting to automatically open the SSO authorization page in your default browser.
If the browser does not open or you wish to use a different device to authorize this request, open the following URL:

https://device.sso.us-west-2.amazonaws.com/

Then enter the code:

FQNH-MVQL
Successfully logged into Start URL: https://mycompany.awsapps.com/start
Added mycompany_sandbox_SuperAdmin
Added mycompany_cool-new-product-dev_Admin
Added mycompany_cool-new-product-test_PowerUser
Added mycompany_cool-new-product-prod_ReadOnly
Added mycompany_special_snowflake_client-dev_Admin
Added mycompany_special_snowflake_client-test_PowerUser
Added mycompany_special_snowflake_client-stage_ReadOnly
Added mycompany_special_snowflake_client-prod_ReadOnly
```
