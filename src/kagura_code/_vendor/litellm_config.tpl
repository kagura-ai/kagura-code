model_list:
{%- for m in models %}
  - model_name: {{ m.alias }}
    litellm_params:
      # ollama_chat/ provider lets LiteLLM honor Ollama-native params like
      # num_ctx, which is required to unlock the daemon's full context cap.
      # The openai/ provider does NOT forward num_ctx, so we cannot use it
      # even though Ollama exposes an OpenAI-compatible endpoint.
      model: ollama_chat/{{ m.ollama_model }}
      api_base: {{ ollama_api_base }}
      num_ctx: {{ m.num_ctx }}
{%- endfor %}
{%- if fallback %}
  - model_name: "*"
    litellm_params:
      model: ollama_chat/{{ fallback.ollama_model }}
      api_base: {{ ollama_api_base }}
      num_ctx: {{ fallback.num_ctx }}
{%- endif %}

general_settings:
  master_key: {{ master_key }}

litellm_settings:
  drop_params: true
  set_verbose: false
