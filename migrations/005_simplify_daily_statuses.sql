UPDATE applications
SET status = CASE status
    WHEN 'Saved' THEN 'Applied'
    WHEN 'Confirmation Received' THEN 'Waiting'
    WHEN 'Follow-up Needed' THEN 'Waiting'
    WHEN 'Assessment' THEN 'Interview / Assessment'
    WHEN 'Interview Scheduled' THEN 'Interview / Assessment'
    WHEN 'No Response' THEN 'Waiting'
    WHEN 'Offer' THEN 'Action Needed'
    ELSE status
END
WHERE status IN (
    'Saved',
    'Confirmation Received',
    'Follow-up Needed',
    'Assessment',
    'Interview Scheduled',
    'No Response',
    'Offer'
);

UPDATE applications
SET next_action = 'Wait'
WHERE status = 'Waiting'
  AND COALESCE(TRIM(next_action), '') = '';

UPDATE applications
SET next_action = 'No action',
    follow_up_date = ''
WHERE status = 'Rejected';
