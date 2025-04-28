import { ServerConnection } from '@jupyterlab/services';
import { URLExt } from '@jupyterlab/coreutils';
import { MetadataForm } from '@jupyterlab/metadataform';

export async function requestAPI<T>(
  endpoint: string,
  init: RequestInit = {}
): Promise<T> {
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(
    settings.baseUrl,
    'jupyter-workflow',
    endpoint
  );
  let response: Response;
  try {
    response = await ServerConnection.makeRequest(requestUrl, init, settings);
  } catch (error) {
    throw new ServerConnection.NetworkError(error as TypeError);
  }
  const data = await response.json();
  if (!response.ok) {
    throw new ServerConnection.ResponseError(response, data);
  }
  return data;
}

export namespace WorkflowHandlers {
  import IMetadataSchema = MetadataForm.IMetadataSchema;

  export async function getSchema(): Promise<IMetadataSchema> {
    return requestAPI<IMetadataSchema>('schema');
  }
}
