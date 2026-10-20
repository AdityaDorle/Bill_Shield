-- Run once in the Supabase SQL editor. Then enable Authentication > Anonymous sign-ins.
-- Publishable key + authenticated user JWT only. No service-role key is needed.
begin;
create table if not exists public.bills (
 id uuid primary key, owner_id uuid not null references auth.users(id) on delete cascade,
 provider text not null, currency text not null, bill_date text not null,
 input_json text not null, masked_file_link text, created_at text not null,
 unique(id, owner_id)
);
create table if not exists public.line_items (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null,
 position integer not null, description text not null, amount_cents bigint not null, kind text not null,
 unique(id,owner_id), foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade
);
create table if not exists public.promises (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null,
 expected_cents bigint not null, source text, valid_from text,
 unique(id,owner_id), foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade
);
create table if not exists public.findings (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null, promise_id uuid not null,
 verdict text not null, calculation_json text not null, created_at text not null,
 unique(id,owner_id), foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade,
 foreign key(promise_id,owner_id) references public.promises(id,owner_id) on delete cascade
);
create table if not exists public.finding_lines (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null, finding_id uuid not null, line_id uuid not null,
 foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade,
 foreign key(finding_id,owner_id) references public.findings(id,owner_id) on delete cascade,
 foreign key(line_id,owner_id) references public.line_items(id,owner_id) on delete cascade
);
create table if not exists public.draft_messages (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null, finding_id uuid not null,
 draft_text text not null, tone text not null, created_at text not null, unique(id,owner_id),
 foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade,
 foreign key(finding_id,owner_id) references public.findings(id,owner_id) on delete cascade
);
create table if not exists public.message_lines (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null, message_id uuid not null, line_id uuid not null,
 foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade,
 foreign key(message_id,owner_id) references public.draft_messages(id,owner_id) on delete cascade,
 foreign key(line_id,owner_id) references public.line_items(id,owner_id) on delete cascade
);
create table if not exists public.message_events (
 id uuid primary key, owner_id uuid not null, bill_id uuid not null, message_id uuid not null,
 action text not null check(action in ('copied','email_opened','sent','edited')),
 event_time text not null, final_text text not null, words_changed integer not null,
 foreign key(bill_id,owner_id) references public.bills(id,owner_id) on delete cascade,
 foreign key(message_id,owner_id) references public.draft_messages(id,owner_id) on delete cascade
);
do $$
declare t text;
begin
 foreach t in array array['bills','line_items','promises','findings','finding_lines','draft_messages','message_lines','message_events']
 loop
  execute format('alter table public.%I enable row level security',t);
  execute format('drop policy if exists own_rows on public.%I',t);
  execute format('create policy own_rows on public.%I for all to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id)',t);
  execute format('create index if not exists %I on public.%I(owner_id)',t || '_owner_idx',t);
  execute format('grant select,insert,delete on public.%I to authenticated',t);
  execute format('revoke all on public.%I from anon',t);
 end loop;
end $$;

create or replace function public.save_records(records jsonb) returns void
language plpgsql security invoker set search_path = public as $$
declare t text;
begin
 if auth.uid() is null then raise exception 'Authentication required'; end if;
 -- Fixed dependency order; table names never come from input.
 foreach t in array array['bills','line_items','promises','findings','finding_lines','draft_messages','message_lines','message_events']
 loop
  if records ? t then
   execute format('insert into public.%I select * from jsonb_populate_recordset(null::public.%I, $1)',t,t) using records->t;
  end if;
 end loop;
end $$;
revoke all on function public.save_records(jsonb) from public,anon;
grant execute on function public.save_records(jsonb) to authenticated;

insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('masked-bills','masked-bills',false,1048576,array['image/svg+xml'])
on conflict (id) do nothing;
drop policy if exists own_bill_files on storage.objects;
create policy own_bill_files on storage.objects for all to authenticated
using (bucket_id='masked-bills' and (storage.foldername(name))[1]=(select auth.uid())::text)
with check (bucket_id='masked-bills' and (storage.foldername(name))[1]=(select auth.uid())::text);
commit;
