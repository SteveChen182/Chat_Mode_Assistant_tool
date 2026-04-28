

# Models

Below are the available models to be used in GNAI

| Model                      | Aliases                                                   | Provider  | Available APIs                                                                           | Price per 1M tokens                |
| -------------------------- | --------------------------------------------------------- | --------- | ---------------------------------------------------------------------------------------- | ---------------------------------- |
| claude-4-6-sonnet          | claude-sonnet, claude-sonnet-4-6                          | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $3.0/$15.0, Cache: $0.3/$3.75 |
| claude-4-5-sonnet          | claude-sonnet-4-5, claude-sonnet-4-5-20250929             | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $3.0/$15.0, Cache: $0.3/$3.75 |
| claude-4-5-sonnet-thinking |                                                           | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $3.0/$15.0, Cache: $0.3/$3.75 |
| claude-4-5-haiku           | claude-haiku, claude-haiku-4-5, claude-haiku-4-5-20251001 | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $1.0/$5.0, Cache: $0.1/$1.25  |
| claude-4-5-haiku-thinking  | claude-haiku-4-5-thinking                                 | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $1.0/$5.0, Cache: $0.1/$1.25  |
| claude-4-5-opus            | claude-opus, claude-opus-4-5, claude-opus-4-5-20251101    | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $5.0/$25.0, Cache: $0.5/$6.25 |
| claude-4-5-opus-thinking   | claude-opus-4-5-thinking                                  | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $5.0/$25.0, Cache: $0.5/$6.25 |
| claude-4-6-sonnet-thinking |                                                           | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $3.0/$15.0, Cache: $0.3/$3.75 |
| claude-4-6-opus            | claude-opus-4-6                                           | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $5.0/$25.0, Cache: $0.5/$6.25 |
| claude-4-6-opus-thinking   | claude-opus-4-6-thinking                                  | anthropic | [/providers/anthropic](https://gpusw-docs.intel.com/services/gnai/developer/api/#anthropic) | I/O: $5.0/$25.0, Cache: $0.5/$6.25 |
| gpt-4.1                    |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $2.0/$8.0, Cache: $0.5        |
| gpt-4o                     |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $2.5/$10.0, Cache: $1.25      |
| gpt-5-mini                 |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $0.25/$2.0, Cache: $0.025     |
| gpt-5-nano                 |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $0.05/$0.4, Cache: $0.005     |
| gpt-5.1                    |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.25/$10.0, Cache: $0.125    |
| gpt-5.1-codex              |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.25/$10.0, Cache: $0.125    |
| gpt-5.1-codex-max          |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.25/$10.0, Cache: $0.125    |
| gpt-5.2                    |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.75/$14.0, Cache: $0.175    |
| gpt-5.2-codex              |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.75/$14.0, Cache: $0.175    |
| gpt-5.3-codex              |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.75/$14.0, Cache: $0.175    |
| gpt-5.4                    |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $2.5/$15.0, Cache: $0.25      |
| gpt-5.4-mini               |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $0.75/$4.5, Cache: $0.075     |
| gpt-5.4-nano               |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $0.2/$1.25, Cache: $0.02      |
| o3                         |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $2.0/$8.0, Cache: $0.5        |
| o3-mini                    |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.1/$4.4, Cache: $0.55       |
| o4-mini                    |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O: $1.1/$4.4, Cache: $0.275      |
| text-embedding-3-large     |                                                           | openai    | [/providers/openai](https://gpusw-docs.intel.com/services/gnai/developer/api/#openai)       | I/O:$0.13/$N/A                   |
