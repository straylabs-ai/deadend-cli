# Web application testing environment

## Building a requester 
To test different payloads and requests in an web application, it is necessary to have an environment capable of acting as a normal user. Vulnerabilities are dependent on different variables that could be tweaked. the different approaches to testing a specific vulnerability is bound to each specific web application. The cookies, sessions, tokens and their name could all be different depending on the target. 

The only way to take into account all this different use-cases, was to use a real browser component. You might have guessed it: an automation browser. Hence the usage of [https://playwright.dev/python/](https://playwright.dev/python/). 

***Why Playwright and not something else ?*** Playwright has mutliple interesting features for automating web application testing. 
- Support for multiple languages (JS, Python)
- Network interception to capture, modify and simulate requests. 
- Works great with multiple browsers. 
- Robust auto-wait features. 


## Handling cookies, authentication and credentials using semantic memory and persisting the Webapp state
Depending on the website, there is multiple ways to authenticate. To be able to create an agent that supports all different types of authentications (all cases that we can see in the wild), using a testing framework is necessary (this is the easiest way we found to do it fast and efficiently) hence ***playwright***. 

The implementation is thought of as the following: 
- We have a global reusable credentials for testing. It is a JSON file that includes some arbitrary and changeable credentials that are used to connect to a target. This file should be available and changeable in the cache folder : `~/.cache/deadend/memory/global/reusable_credentials.json`.
- The agent can use these credentials to login in or sign up to a web app or API for further testing. 
- When the agent sends a login request, he should be able to extract the authentication mechanism (either by session ID, or auth token if it's a Single Page Application). 
- These information, and other cookies such as CSRFs and other tokens necessary for the application must be able to be used. This is taken into account in Playwright's context. 
- To persist the state between multiple request, we specify an ID to each Playwright instance defined by the `PlaywrightRequester` object and managed by `PlaywrightSessionManager` object.
- Finally after each call to a request, cookies and localstorage are also saved in the cache for further analysis or reuse if necessary and that's what defines the persistence of the tokens and cookies as a semantic memory (simple file). To do so we added functions to detect access tokens and other different types of tokens so that they be exported and reused later.

## Agent's handling of secrets
The agent handles the accounts set for testing. 







