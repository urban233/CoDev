import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection, getEntry } from 'astro:content';

export const getStaticPaths: GetStaticPaths = async () => {
  const entries = await getCollection('docs');
  return entries
    .filter((entry) => entry.id !== 'index')
    .map((entry) => ({ params: { slug: entry.id } }));
};

export const GET: APIRoute = async ({ params }) => {
  const entry = await getEntry('docs', params.slug ?? '');
  return new Response(entry?.body ?? '', {
    headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
  });
};
