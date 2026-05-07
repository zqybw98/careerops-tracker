# Deployment Guide

This project is ready to deploy on Streamlit Community Cloud as a lightweight
public portfolio demo.

## Recommended Target

- Platform: Streamlit Community Cloud
- Repository: `zqybw98/careerops-tracker`
- Branch: `main`
- Entry point: `app.py`
- Python version: `3.13`
- Dependency file: `requirements.txt`

## Deploy Steps

1. Go to `https://share.streamlit.io`.
2. Sign in with GitHub.
3. Click `Create app`.
4. Choose `Yup, I have an app`.
5. Select this repository:

   ```text
   zqybw98/careerops-tracker
   ```

6. Set the branch to:

   ```text
   main
   ```

7. Set the main file path to:

   ```text
   app.py
   ```

8. Open `Advanced settings`.
9. Select Python `3.13`.
10. Choose a readable app URL, for example:

    ```text
    careerops-tracker
    ```

11. Click `Deploy`.

After deployment, the app URL should look like:

```text
https://careerops-tracker.streamlit.app
```

If that subdomain is unavailable, Streamlit will let you choose another one.

## Post-Deploy README Update

After the app is live, update the README near the top with:

```markdown
[Live Demo](https://your-app-name.streamlit.app)
```

Use the actual Streamlit app URL generated during deployment.

## Deployment Notes

- The app stores data in SQLite under `data/`.
- On Streamlit Community Cloud, this storage is suitable for a portfolio demo,
  not long-term production persistence.
- The `Load sample applications` button in the Data tab lets reviewers populate
  the dashboard quickly.
- Personal job search data should not be committed to the repository.

## Troubleshooting

- If the app fails to install dependencies, check the Streamlit Cloud build logs.
- If the app uses the wrong Python version, redeploy it and select Python `3.13`
  in `Advanced settings`.
- If the dashboard is empty, open the Data tab and click `Load sample applications`.
