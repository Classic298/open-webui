import { WEBUI_API_BASE_URL } from '$lib/constants';

export const pruneData = async (
  token: string,
  days: number | null,
  exempt_archived_chats: boolean,
  exempt_chats_in_folders: boolean
) => {
  let error = null;

  const res = await fetch(`${WEBUI_API_BASE_URL}/prune/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify({
      days,
      exempt_archived_chats,
      exempt_chats_in_folders
    })
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      console.log(err);
      return null;
    });

  if (error) {
    throw error;
  }

  return res;
};
