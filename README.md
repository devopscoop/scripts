# AWS tools

## aws_configure_all_sso.sh

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
Added Hideous Monolith Dev_Admin
Added Hideous Monolith Prod_ReadOnly
Added sandbox_SuperAdmin
Added cool-new-product-dev_Admin
Added cool-new-product-test_PowerUser
Added cool-new-product-prod_ReadOnly
Added special_snowflake_client-dev_Admin
Added special_snowflake_client-test_PowerUser
Added special_snowflake_client-stage_ReadOnly
Added special_snowflake_client-prod_ReadOnly
```
