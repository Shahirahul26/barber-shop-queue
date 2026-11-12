// Firebase Phone Auth Configuration (10,000 Free SMS / month)
// Get these values from: Firebase Console -> Project Settings -> General -> Your apps -> Web app
window.firebaseConfig = {
  apiKey: "AawNgEquBlJoqom7tOFWBC7xQgAxUiYNRQhsmTQn7kRDOTNPbUmcotSzHjUsmp2lwpwHuyPvs4P9WzFEtchh-ALkuHIJxvufnVKT3zAYYAKD6DhdWVqpUFfkFIN5F50qisMqT3AtCp_NdFa7Uh8Y0w6OJg",
  authDomain: "trimtime-barber.firebaseapp.com",
  projectId: "trimtime",
  storageBucket: "trimtime-barber.appspot.com",
  messagingSenderId: "",
  appId: ""
};

(function initFirebase() {
  if (typeof firebase !== "undefined" && window.firebaseConfig && window.firebaseConfig.apiKey) {
    try {
      if (!firebase.apps.length) {
        firebase.initializeApp(window.firebaseConfig);
      }
    } catch (err) {
      console.warn("Firebase initialization:", err);
    }
  }
})();

